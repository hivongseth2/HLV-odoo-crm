"""Đọc các chuyến đã chạy -> mẫu đo -> ghi ĐỀ XUẤT định mức lên từng cụm.

Phép tính nằm ở ``tools/vtracking_calibration`` (thuần, có test). File này chỉ lo đọc dữ
liệu từ Odoo và ghi kết quả — không quyết định con số nào.

Chạy hằng ngày bằng cron. Không bao giờ tự sửa định mức: chỉ ghi đề xuất, người điều phối
bấm áp dụng.
"""

import logging
from datetime import timedelta

from odoo import fields
from odoo.addons.hlv_geo_utils.tools.geo_distance import haversine_km

from ..tools.vtracking_calibration import suggestions, trip_samples

_logger = logging.getLogger(__name__)

# Cửa sổ lấy mẫu. Đủ dài để cụm ít chuyến vẫn gom được mẫu, đủ ngắn để phản ánh đường sá
# và đội xe hiện tại chứ không phải của mùa trước.
LOOKBACK_DAYS = 60

# Xe về trong bán kính này quanh điểm xuất phát là coi như đã về kho.
BACK_AT_HUB_KM = 0.5
# Sau điểm cuối bao lâu thì thôi tìm xe về: quá khung này thường là xe đi việc khác.
BACK_SEARCH = timedelta(hours=5)


def calibrate_company(env, company, today=None):
    """Tính lại đề xuất cho mọi cụm của công ty. Trả về số cụm có đề xuất."""
    today = today or fields.Date.context_today(env['hlv.vtracking.zone'])
    zones = env['hlv.vtracking.zone'].sudo().search([('company_id', '=', company.id)])
    if not zones:
        return 0
    samples, plan_count = collect_samples(env, company, today)
    current = {
        zone.id: {
            'hub': zone.hub_to_first_minutes,
            'leg': zone.median_leg_minutes,
            'return': zone.return_minutes,
        } for zone in zones
    }
    result = suggestions(samples, current)
    now = fields.Datetime.now()
    for zone in zones:
        zone.write(zone._calibration_values(result.get(zone.id, {}), plan_count, now))
    with_suggestion = len(zones.filtered('calib_has_suggestion'))
    _logger.info(
        'V-Tracking hiệu chỉnh %s: %s chuyến, %s mẫu, %s cụm có đề xuất',
        company.name, plan_count, len(samples), with_suggestion,
    )
    return with_suggestion


def collect_samples(env, company, today, days=LOOKBACK_DAYS):
    """Mẫu đo từ mọi chuyến có số thực tế trong ``days`` ngày gần nhất.

    Trả về ``(samples, plan_count)``. Điểm chở về (giao hụt) không lấy làm mẫu: xe có tới
    nhưng thời gian ở đó không phải thời gian GIAO.
    """
    plans = env['hlv.vtracking.plan'].sudo().search([
        ('company_id', '=', company.id),
        ('state', '!=', 'cancelled'),
        ('date', '>=', today - timedelta(days=days)),
        ('date', '<=', today),
        ('actual_line_count', '>', 0),
    ])
    samples = []
    for plan in plans:
        stops = [
            {
                'delivered_at': line.delivered_at,
                'zone_id': line.zone_id.id or None,
                'point': (line.latitude, line.longitude) if line.latitude and line.longitude else None,
                'key': line.address_id.id or None,
            }
            for line in plan.line_ids
            if line.delivered and line.delivered_at and not line.returned
        ]
        samples += trip_samples(
            plan.actual_start_at, plan.actual_start_source == 'received', stops,
            back_at_hub(plan),
        )
    return samples, len(plans)


def back_at_hub(plan):
    """Lúc xe quay lại gần điểm xuất phát sau điểm giao cuối, đọc từ GPS. None nếu không
    biết — thiếu điểm xuất phát, thiếu GPS (lịch sử bị dọn sau hạn lưu trữ), hoặc xe
    không về trong khung ``BACK_SEARCH``."""
    place = plan.start_place_id
    if not (place.has_coords and plan.actual_end_at and plan.vehicle_id):
        return None
    hub = (place.latitude, place.longitude)
    end_at = fields.Datetime.to_datetime(plan.actual_end_at)
    positions = plan.env['hlv.vtracking.position'].sudo().search([
        ('vehicle_id', '=', plan.vehicle_id.id),
        ('ts', '>', end_at),
        ('ts', '<=', end_at + BACK_SEARCH),
    ], order='ts')
    for position in positions:
        if not (position.latitude and position.longitude):
            continue
        distance = haversine_km((position.latitude, position.longitude), hub)
        if distance is not None and distance <= BACK_AT_HUB_KM:
            return position.ts
    return None
