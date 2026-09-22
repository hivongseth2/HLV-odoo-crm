"""Dựng dữ liệu kế hoạch giao hàng ở dạng dict.

Dùng chung cho màn bản đồ và API cho AI: hai nơi cùng mô tả một kế hoạch thì phải mô tả
bằng cùng một bộ khoá. Tách khỏi model vì đây là việc trình bày, không phải quy tắc nghiệp
vụ — model chỉ giữ dữ liệu và ràng buộc.
"""

from odoo import fields

from ..tools.vtracking_partner import root_partner_name
from ..tools.vtracking_route import estimate_legs

SESSION_LABELS = {
    'morning': 'Sáng',
    'afternoon': 'Chiều',
    'full_day': 'Cả ngày',
}


def iso_datetime(value):
    """Datetime của Odoo -> chuỗi ISO, hoặc None. Giờ là UTC như Odoo lưu."""
    return fields.Datetime.to_string(value) if value else None


def plan_summary(plan):
    """Phần đầu của một kế hoạch: xe, buổi, tổng số, dự kiến, và ô thực tế.

    Ô ``actual_*`` luôn có mặt dù đang rỗng: bên đọc phải thấy rõ "kế hoạch 12 điểm" chưa
    nói gì về việc đã giao mấy điểm.
    """
    return {
        'id': plan.id,
        'name': plan.name,
        'date': fields.Date.to_string(plan.date) if plan.date else None,
        'session': plan.session,
        'session_label': SESSION_LABELS.get(plan.session, ''),
        'state': plan.state,
        'vehicle_id': plan.vehicle_id.id,
        'vehicle_plate': plan.vehicle_id.license_plate or '',
        'driver_user_id': plan.driver_user_id.id or None,
        'driver_name': plan.driver_name or plan.driver_user_id.name or None,
        'driver_mismatch': plan.driver_mismatch or None,
        'line_count': plan.line_count,
        'stop_count': plan.stop_count,
        'amount_total': plan.amount_total,
        'distance_km': plan.distance_km,
        # Lộ trình đường thật: có thì bản đồ vẽ nét liền theo đúng đường xe chạy, không có
        # thì vẽ nét đứt nối thẳng như trước. Luôn trả cả hai con số km chứ không thay thế
        # distance_km: km chim bay là thứ so được giữa MỌI chuyến, kể cả chuyến chưa lấy
        # được đường thật, nên bỏ nó đi là mất khả năng so sánh.
        'road_polyline': plan.road_polyline or None,
        'road_distance_km': plan.road_distance_km or None,
        'road_duration_minutes': plan.road_duration_minutes or None,
        # Thứ tự ghé đã đổi sau lần lấy đường: đường đang vẽ là của thứ tự CŨ, người xem
        # phải biết để không tin vào nó.
        'road_route_stale': plan.road_route_stale or None,
        'drive_minutes': plan.drive_minutes,
        'service_minutes': plan.service_minutes,
        'total_minutes': plan.total_minutes,
        'duration_display': plan.duration_display,
        'missing_coords_count': plan.missing_coords_count,
        'return_minutes': plan.return_minutes,
        'zone_id': plan.zone_id.id or None,
        'zone_name': plan.zone_id.name or None,
        'zone_warning': plan.zone_warning or None,
        # Đếm sẵn để bên gọi không phải duyệt hết line mới biết kế hoạch có xác nhận được
        # không. Còn dòng nào chặn là action_confirm sẽ báo lỗi.
        'procedure_blocked_count': len(plan.line_ids.filtered('procedure_blocked')),
        'no_truck_count': len(plan.line_ids.filtered(lambda line: not line.needs_truck)),
        'has_actual_data': plan.has_actual_data,
        'actual_line_count': plan.actual_line_count,
        'actual_amount_total': plan.actual_amount_total,
        'actual_distance_km': plan.actual_distance_km,
        'actual_returned_count': plan.actual_returned_count,
        'actual_start_at': iso_datetime(plan.actual_start_at),
        'actual_end_at': iso_datetime(plan.actual_end_at),
        # 'done' = thiếu mốc hàng lên xe nên thời lượng thực tế là CẬN DƯỚI.
        'actual_start_source': plan.actual_start_source,
        'actual_duration_display': plan.actual_duration_display or None,
        'variance': plan._variance_summary(),
        'ai_excluded_note': plan.ai_excluded_note or None,
        'start': plan_start(plan),
    }


def plan_start(plan):
    """Điểm xuất phát ở dạng dict, hoặc None khi chưa chọn / chưa có toạ độ.

    Thiếu điểm này thì lộ trình trên bản đồ bắt đầu lơ lửng ở điểm giao đầu tiên.
    """
    place = plan.start_place_id
    if not place.has_coords:
        return None
    return {
        'place_id': place.id,
        'name': place.name,
        'warehouse_id': place.warehouse_id.id or None,
        'latitude': place.latitude,
        'longitude': place.longitude,
    }


def plan_lines(plan, with_legs=False):
    """Các điểm giao theo đúng thứ tự ghé.

    ``seq_no`` đếm cả điểm chưa có toạ độ, nên số hiện trên bản đồ khớp với số trên tờ kế
    hoạch in ra.

    ``with_legs=True`` kèm quãng đường từng chặng và giờ tới cộng dồn (phút tính từ lúc
    xuất phát). Bản đồ không cần nên mặc định tắt; AI cần để biết điểm nào tới lúc nào.
    """
    lines = plan._ordered_lines()
    legs = estimate_legs(**plan._route_kwargs()) if with_legs else []
    result = []
    for index, line in enumerate(lines):
        item = {
            'id': line.id,
            'seq_no': index + 1,
            'reference': line.display_reference,
            'picking_id': line.picking_id.id or None,
            'picking_name': line.picking_id.name or None,
            'sale_order_id': line.sale_order_id.id or line.picking_id.sale_id.id or None,
            'sale_order_name': (line.sale_order_id or line.picking_id.sale_id).name or None,
            'source_name': line.source_name or '',
            'partner_name': root_partner_name(line.partner_id),
            'address': line.address or '',
            'amount': line.amount,
            'latitude': line.latitude or None,
            'longitude': line.longitude or None,
            'zone_id': line.zone_id.id or None,
            'zone_name': line.zone_id.name or None,
            'zone_source': line.zone_source,
            'zone_uncertain': line.zone_uncertain,
            'waiting_picking': line.line_state == 'waiting_picking',
            # Thói quen khách — AI phải đọc được để biết điểm nào đang bị chặn và điểm nào
            # lẽ ra không cần chiếm một chỗ trên xe.
            'procedure_required': line.procedure_required or 'none',
            'procedure_ready': line.procedure_ready,
            'procedure_blocked': line.procedure_blocked,
            'delivery_channel': line.delivery_channel or None,
            'needs_truck': line.needs_truck,
            'extra_service_minutes': line.extra_service_minutes or 0,
            'driver_note': line.driver_note or None,
            # Thực tế — nguồn khác hẳn phần dự kiến ở trên, đừng trộn hai bên.
            'delivered_at': iso_datetime(line.delivered_at),
            'returned': line.returned,
            'return_reason': line.return_reason or None,
            'variance_minutes': line.variance_minutes if line.variance_measured else None,
            'has_coords': line.has_coords,
            'delivered': line.delivered,
        }
        if with_legs:
            item.update(legs[index])
        result.append(item)
    return result


def plans_by_vehicle(env, vehicle_ids, day=None):
    """dict {vehicle_id: [kế hoạch của ngày đó]} — mọi buổi, trừ kế hoạch đã huỷ.

    Trả về MỌI buổi chứ không chỉ buổi hiện tại: người xem cần thấy cả ngày của xe, và
    "bây giờ là buổi nào" là câu hỏi không có câu trả lời rõ ràng lúc 12 giờ trưa.
    """
    Plan = env['hlv.vtracking.plan'].sudo()
    day = day or fields.Date.context_today(Plan)
    plans = Plan.search([
        ('vehicle_id', 'in', list(vehicle_ids)),
        ('date', '=', day),
        ('state', '!=', 'cancelled'),
    ], order='session')
    result = {}
    for plan in plans:
        payload = plan_summary(plan)
        payload['lines'] = plan_lines(plan)
        result.setdefault(plan.vehicle_id.id, []).append(payload)
    return result
