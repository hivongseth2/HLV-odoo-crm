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


def plan_summary(plan):
    """Phần đầu của một kế hoạch: xe, buổi, tổng số, dự kiến, và ô thực tế.

    Ô ``actual_*`` luôn có mặt dù đang rỗng: chúng chờ module shipper điền, và bên đọc
    phải thấy rõ "kế hoạch 12 điểm" chưa nói gì về việc đã giao mấy điểm.
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
        'line_count': plan.line_count,
        'amount_total': plan.amount_total,
        'distance_km': plan.distance_km,
        'drive_minutes': plan.drive_minutes,
        'service_minutes': plan.service_minutes,
        'total_minutes': plan.total_minutes,
        'duration_display': plan.duration_display,
        'missing_coords_count': plan.missing_coords_count,
        'has_actual_data': plan.has_actual_data,
        'actual_line_count': plan.actual_line_count,
        'actual_amount_total': plan.actual_amount_total,
        'actual_distance_km': plan.actual_distance_km,
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
    legs = (
        estimate_legs(plan._route_start(), plan._route_stops(), plan._route_params())
        if with_legs else []
    )
    result = []
    for index, line in enumerate(lines):
        item = {
            'id': line.id,
            'seq_no': index + 1,
            'reference': line.display_reference,
            'picking_id': line.picking_id.id or None,
            'sale_order_id': line.sale_order_id.id or line.picking_id.sale_id.id or None,
            'source_name': line.source_name or '',
            'partner_name': root_partner_name(line.partner_id),
            'address': line.address or '',
            'amount': line.amount,
            'latitude': line.latitude or None,
            'longitude': line.longitude or None,
            'waiting_picking': line.line_state == 'waiting_picking',
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
