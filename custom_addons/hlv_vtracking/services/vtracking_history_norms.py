"""Học định mức từ LỊCH SỬ PHIẾU, không cần kế hoạch.

Vì sao cần: định mức chỉ học được từ chuyến đã chạy, mà kế hoạch trong Odoo mới có từ hôm
nay. Trong khi đó nhật ký quét mã vạch đã ghi hàng nghìn lần giao suốt nhiều tháng — đủ để
đo ngay, thay vì chờ vài tuần cho kế hoạch tích luỹ.

Một "chuyến dựng lại" = các lần quét *hoàn thành đơn* của CÙNG một người trong CÙNG một
ngày, sắp theo giờ quét. Mốc xuất phát là lần quét *nhận hàng* cuối cùng của người đó trong
ngày — cùng định nghĩa với ``actual_start_at`` của kế hoạch, nên hai nguồn mẫu so được với
nhau.

Cụm của mỗi điểm suy theo ĐÚNG thứ tự mà dòng kế hoạch dùng (xem
``models/vtracking_plan_line_zone``): toạ độ địa chỉ giao trước, điểm của khách chỉ là dự
phòng. Đo 22/09/2026 vì sao phải thế: cả ba mã khách của Dongjin Textile đều có phiếu giao
về cả hai nhà máy (Nhơn Trạch và KCN Long Bình, cách nhau 28 km) — hỏi theo khách thì gần
một nửa số phiếu bị gán nhầm cụm, và định mức học từ đó là định mức của cụm khác.

KHÔNG tra toạ độ ở đây: chỉ đọc kho toạ độ đã có. Tra mới là gọi ra ngoài và tốn tiền, mà
đây là việc chạy nền hàng đêm trên hàng nghìn phiếu.

Phép tính nằm ở ``tools/vtracking_calibration`` (thuần, có test); file này chỉ lo đọc dữ
liệu và ghép phiếu với cụm.
"""

import logging
from collections import defaultdict
from datetime import timedelta

from odoo import fields

from ..tools.vtracking_address import address_key
from ..tools.vtracking_calibration import trip_samples
from ..tools.vtracking_channel import needs_company_truck
from ..tools.vtracking_planning import DEFAULT_ZONE_MATCH_KM, nearest_zone
from .vtracking_place_lookup import places_by_root_partner

_logger = logging.getLogger(__name__)

# Cửa sổ nhìn lại. Dài hơn cửa sổ của kế hoạch (60 ngày) vì đây là dữ liệu đã có sẵn: lấy
# rộng để cụm ít chuyến cũng gom đủ mẫu.
LOOKBACK_DAYS = 180
# Một người quét nhiều phiếu trong ngày mới thành chuyến; một điểm thì không đo được chặng.
MIN_STOPS = 2


def history_samples(env, company, today=None, days=LOOKBACK_DAYS):
    """Mẫu đo dựng từ nhật ký quét. Trả ``(samples, trip_count)``.

    Bỏ qua phiếu đã nằm trong một kế hoạch: chỗ đó đã được đếm ở nguồn mẫu của kế hoạch,
    đếm thêm lần nữa là nhân đôi trọng số của đúng những chuyến gần đây nhất.
    """
    today = today or fields.Date.context_today(env['hlv.vtracking.plan'])
    since = fields.Datetime.to_datetime(today - timedelta(days=days))
    Scan = env['barcode.scan.log'].sudo()

    completes = Scan.search([
        ('scan_type', '=', 'complete'), ('status', '=', 'success'),
        ('scan_time', '>=', since), ('picking_id', '!=', False), ('user_id', '!=', False),
    ], order='scan_time asc')
    if not completes:
        return [], 0

    planned = set(env['hlv.vtracking.plan.line'].sudo().search([
        ('picking_id', 'in', completes.picking_id.ids),
    ]).mapped('picking_id').ids)
    places = places_by_root_partner(env, company)
    zone_points = _zone_points(env, company)
    coords_by_key = _coords_by_address_key(env)
    near_km = company.vtracking_zone_match_km or DEFAULT_ZONE_MATCH_KM

    no_place = env['hlv.vtracking.place'].browse()
    trips = defaultdict(list)
    for scan in completes:
        picking = scan.picking_id
        if picking.id in planned or not _went_by_company_truck(picking):
            continue
        place = places.get(picking.partner_id.commercial_partner_id.id, no_place)
        point = coords_by_key.get(address_key(picking._vtracking_delivery_address()))
        if not point and place.has_coords:
            point = (place.latitude, place.longitude)
        zone_id = _zone_of(point, zone_points, near_km) or place.zone_id.id
        if not zone_id:
            continue
        trips[(scan.user_id.id, scan.scan_time.date())].append({
            'delivered_at': scan.scan_time,
            'zone_id': zone_id,
            'point': point,
            'key': _stop_key(point, place),
        })

    departures = _departures(Scan, since)
    samples, trip_count = [], 0
    for (user_id, day), stops in trips.items():
        if len(stops) < MIN_STOPS:
            continue
        trip_count += 1
        start_at = departures.get((user_id, day))
        samples += trip_samples(start_at, bool(start_at), stops)
    _logger.info('V-Tracking: %s chuyến dựng từ nhật ký quét, %s mẫu đo.',
                 trip_count, len(samples))
    return samples, trip_count


def _went_by_company_truck(picking):
    """Phiếu này có phải xe công ty chạy không.

    Khách ghé lấy, gửi chuyển phát nhanh, book Grab: kho vẫn quét *hoàn thành đơn* lúc bàn
    giao ngay tại kho, nên nếu tính vào thì được một "điểm giao" mất 0 phút nằm đúng chỗ
    kho — kéo định mức chặng xuống thấp giả tạo.

    Không đọc được kênh thì coi như xe công ty: ô trống nghĩa là "như mọi khi".
    """
    order = picking.sale_id
    if not order:
        return True
    return needs_company_truck(order._vtracking_delivery_channel() or None)


def _zone_points(env, company):
    """Các điểm đã biết chắc thuộc cụm nào — tập mẫu để so khoảng cách.

    Cùng tập mẫu mà dòng kế hoạch dùng, để hai nơi không ra hai đáp án cho cùng một chỗ.
    """
    places = env['hlv.vtracking.place'].sudo().search([
        ('zone_id', '!=', False),
        ('has_coords', '=', True),
        ('company_id', '=', company.id),
    ])
    return [(place.zone_id.id, (place.latitude, place.longitude)) for place in places]


def _coords_by_address_key(env):
    """``{khoá địa chỉ: (vĩ độ, kinh độ)}`` từ kho toạ độ đã tra. Không tra thêm."""
    addresses = env['hlv.vtracking.address'].sudo().search([
        ('has_coords', '=', True), ('address_key', '!=', False),
    ])
    return {address.address_key: (address.latitude, address.longitude)
            for address in addresses}


def _zone_of(point, zone_points, near_km):
    """Cụm của một toạ độ, hoặc ``None`` khi không có toạ độ / không điểm mẫu nào đủ gần.

    Chỉ nhận khi điểm mẫu gần nhất nằm trong ngưỡng ``near_km``. ``nearest_zone`` vẫn trả
    về cụm gần nhất dù xa mấy — kế hoạch dùng được vì có cờ "cụm chưa chắc" cho người soát,
    còn ở đây thì không: một lần giao Biên Hoà gán nhầm vào Nhơn Trạch là một mẫu rác nằm
    im trong định mức, không ai thấy để sửa.
    """
    if not point:
        return None
    zone_id, _distance, confident = nearest_zone(point, zone_points, near_km)
    return zone_id if confident else None


def _stop_key(point, place):
    """Khoá gom các phiếu giao CÙNG MỘT CHỖ trong một chuyến thành một điểm dừng.

    Theo toạ độ trước, vì một khách có thể giao ở hai nơi; chỉ khi không có toạ độ mới gom
    theo điểm của khách.
    """
    if point:
        return ('geo', round(point[0], 5), round(point[1], 5))
    return ('place', place.id if place else 0)


def _departures(Scan, since):
    """dict {(người, ngày): lúc quét NHẬN hàng cuối cùng} — mốc xe rời kho.

    Lấy lần cuối chứ không lấy lần đầu: xe chỉ đi khi đã nhận xong phiếu cuối của chuyến.
    """
    receives = Scan.search([
        ('scan_type', '=', 'receive'), ('status', '=', 'success'),
        ('scan_time', '>=', since), ('user_id', '!=', False),
    ], order='scan_time asc')
    result = {}
    for scan in receives:
        result[(scan.user_id.id, scan.scan_time.date())] = scan.scan_time
    return result
