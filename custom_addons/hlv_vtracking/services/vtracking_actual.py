"""Đọc số THỰC TẾ của một kế hoạch từ phiếu giao và từ lịch sử GPS.

Nguyên tắc: **không suy số thực tế từ kế hoạch.** Kế hoạch nói xe nên tới lúc 9:10; thực
tế nói phiếu được xác nhận lúc 9:37. Trộn hai nguồn vào nhau là mất luôn khả năng đối
chiếu — mà đối chiếu chính là chỗ định mức được sửa cho đúng.

Nguồn từng con số:

* ``shipper_receive_time`` — lúc shipper NHẬN hàng tại kho. Đây là mốc xuất phát đáng tin
  nhất: xe chỉ chạy sau khi hàng đã lên xe.
* ``date_done`` — lúc phiếu được xác nhận hoàn tất, tức lúc shipper bấm xong tại chỗ
  khách. Đây là mốc GIAO XONG, và cũng chính là mốc mà định mức cụm được đo từ đó.
* ``shipper_returned`` — hàng chở về kho: một điểm ĐÃ ĐI mà KHÔNG giao được. Đây là dữ
  liệu quý nhất để học và cũng là dữ liệu hay bị bỏ qua nhất.
* ``hlv.vtracking.position`` — GPS của chính module này, cho km thực chạy.
"""

import logging
from datetime import timedelta

from odoo import fields
from odoo.addons.hlv_geo_utils.tools.geo_distance import total_path_km

from ..tools.vtracking_actual import leg_variance, minutes_between
from ..tools.vtracking_route import estimate_legs

_logger = logging.getLogger(__name__)

# Nới hai đầu khung giờ lấy GPS. Xe rời kho trước khi phiếu đầu được xác nhận, và về kho
# sau khi phiếu cuối xong — cắt đúng hai mốc đó thì km thực chạy luôn thiếu cả chặng đi
# lẫn chặng về.
GPS_PADDING = timedelta(minutes=30)


def fill_plan_actuals(plans):
    """Đọc lại toàn bộ số thực tế cho các kế hoạch. Trả về số kế hoạch có dữ liệu.

    Chạy lại bao nhiêu lần cũng được: mỗi lần đều đọc từ nguồn, không cộng dồn.
    """
    filled = 0
    for plan in plans:
        lines = plan._ordered_lines()
        for line in lines:
            line.write(line_actual_values(line))
        plan.write(plan_actual_values(plan, lines))
        write_variance(plan, lines)
        filled += 1 if plan.actual_line_count or plan.actual_start_at else 0
    return filled


def write_variance(plan, lines):
    """Ghi chênh lệch giờ tới của từng điểm: thực tế trừ kế hoạch, tính bằng phút.

    Phải chạy SAU khi ``actual_start_at`` đã ghi xong: cả hai vế đều đo bằng số phút tính từ
    lúc xuất phát, nên thiếu mốc xuất phát là không so được gì.

    Dương = tới CHẬM hơn kế hoạch. Điểm không đo được để trống chứ không ghi 0 — 0 nghĩa là
    đúng y hẹn, khác hẳn "không biết".
    """
    planned = [leg['arrive_offset_minutes'] for leg in estimate_legs(**plan._route_kwargs())]
    actual = [minutes_between(plan.actual_start_at, line.delivered_at) for line in lines]
    for line, item in zip(lines, leg_variance(planned, actual)):
        # Integer của Odoo không lưu được NULL: "không đo được" và "đúng y hẹn" đều thành 0.
        # Cờ riêng là cách duy nhất để báo cáo độ chính xác không đếm điểm chưa đo là đúng hẹn.
        line.write({
            'variance_minutes': item['variance'] or 0,
            'variance_measured': item['variance'] is not None,
        })
    return True


def line_actual_values(line):
    """Giá trị thực tế của MỘT điểm giao, đọc từ phiếu.

    Dòng chưa có phiếu xuất thì mọi ô thực tế về rỗng — chưa có phiếu nghĩa là chưa có gì
    xảy ra, không phải "đã giao 0 đồng".
    """
    picking = line.picking_id
    if not picking:
        return {'delivered': False, 'delivered_at': False, 'returned': False,
                'return_reason': False, 'received_at': False, 'shipper_id': False}
    delivered = picking.state == 'done'
    return {
        'delivered': delivered,
        # Chỉ lấy date_done khi phiếu THẬT SỰ xong: phiếu huỷ cũng có thể mang date_done.
        'delivered_at': picking.date_done if delivered else False,
        'returned': picking.shipper_returned,
        'return_reason': picking.shipper_return_reason or False,
        'received_at': picking.shipper_receive_time or False,
        'shipper_id': (picking.shipper_received_by or picking.shipper_user_id).id or False,
    }


def plan_actual_values(plan, lines):
    """Tổng hợp thực tế ở mức kế hoạch.

    ``actual_start_at`` ưu tiên lúc shipper nhận hàng; không có thì lùi về điểm giao xong
    sớm nhất. Lùi như vậy làm thời lượng chuyến ngắn hơn thực tế, nên chỗ nào dùng con số
    này phải biết nó là **cận dưới** — xem ``actual_start_source``.
    """
    delivered = lines.filtered('delivered')
    received = [line.received_at for line in lines if line.received_at]
    done_at = [line.delivered_at for line in delivered if line.delivered_at]

    start_at = min(received) if received else (min(done_at) if done_at else False)
    end_at = max(done_at) if done_at else False
    values = {
        'actual_line_count': len(delivered),
        'actual_returned_count': len(lines.filtered('returned')),
        'actual_amount_total': sum(delivered.mapped('amount')),
        'actual_start_at': start_at,
        'actual_end_at': end_at,
        'actual_start_source': 'received' if received else ('done' if done_at else 'none'),
    }
    values['actual_distance_km'] = gps_distance_km(plan, start_at, end_at)
    return values


def gps_distance_km(plan, start_at, end_at):
    """Km thực chạy của xe trong khung giờ của chuyến, đo từ lịch sử GPS.

    Trả về 0.0 khi thiếu mốc giờ hoặc khi lịch sử đã bị tác vụ dọn xoá (mặc định giữ 30
    ngày). **0.0 nghĩa là "không đo được", không phải "xe không chạy"** — kế hoạch cũ hơn
    hạn lưu trữ sẽ luôn ra 0.
    """
    if not (start_at and end_at and plan.vehicle_id):
        return 0.0
    positions = plan.env['hlv.vtracking.position'].sudo().search(
        [
            ('vehicle_id', '=', plan.vehicle_id.id),
            ('ts', '>=', fields.Datetime.to_datetime(start_at) - GPS_PADDING),
            ('ts', '<=', fields.Datetime.to_datetime(end_at) + GPS_PADDING),
        ],
        order='ts',
    )
    points = [
        (position.latitude, position.longitude) for position in positions
        if position.latitude and position.longitude
    ]
    return round(total_path_km(points), 1) if len(points) > 1 else 0.0
