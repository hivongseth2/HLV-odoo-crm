"""Dữ liệu cho trang `/giao-hang` — nơi người bán hàng xem chuyến và xin AI xếp lịch.

Vì sao cắt riêng khỏi ``plan_payload``: người bán hàng cần ÍT hơn hẳn người điều phối. Họ
cần biết "xe nào đang đi đâu, đơn của tôi nằm chuyến nào, đơn nào chưa được xếp" — không
cần định mức, không cần phân tích lệch giờ. Trả nguyên khối của điều phối ra trang ngoài
vừa nặng vừa lộ thứ không cần lộ (tiền hàng của khách người khác).

Mọi truy vấn ở đây chạy bằng ``sudo``: người bán hàng không có quyền trên model kế hoạch,
và cũng không nên có — họ chỉ được xem đúng những ô liệt kê trong file này.
"""

from odoo import fields

from ..tools.vtracking_request import OPEN_STATES
from . import plan_payload

# Số ngày nhìn tới trước trong ô "đơn của tôi chưa xếp". Xa hơn nữa thì chưa ai xếp chuyến,
# liệt kê ra chỉ làm nhiễu.
UNPLANNED_HORIZON_DAYS = 14
MAX_UNPLANNED = 40
MAX_MY_REQUESTS = 15


def board_data(env, day=None):
    """Toàn bộ dữ liệu một lần vẽ trang: chuyến trong ngày, xe, đơn của tôi, yêu cầu của tôi."""
    day = day or fields.Date.context_today(env['hlv.vtracking.plan'])
    company = env.company
    vehicles = env['fleet.vehicle'].sudo().search([
        ('vtracking_enabled', '=', True),
        ('company_id', 'in', [company.id, False]),
    ], order='license_plate')
    plans_by_vehicle = plan_payload.plans_by_vehicle(env, vehicles.ids, day)
    my_order_ids = set(_my_order_ids(env))

    return {
        'date': fields.Date.to_string(day),
        'today': fields.Date.to_string(fields.Date.context_today(env['hlv.vtracking.plan'])),
        'user_name': env.user.name,
        'tile_url': company.vtracking_map_tile_url or '',
        'tile_attribution': company.vtracking_map_attribution or '',
        'vehicles': [_vehicle_block(vehicle) for vehicle in vehicles],
        'plans': [
            _plan_block(plan, my_order_ids)
            for vehicle in vehicles
            for plan in plans_by_vehicle.get(vehicle.id, [])
        ],
        'my_unplanned': my_unplanned_orders(env),
        'my_requests': my_requests(env),
    }


def vehicle_positions(env):
    """Chỉ vị trí xe — trang gọi lại mỗi nửa phút, không kéo theo cả kế hoạch."""
    vehicles = env['fleet.vehicle'].sudo().search([
        ('vtracking_enabled', '=', True),
        ('company_id', 'in', [env.company.id, False]),
    ], order='license_plate')
    return {'vehicles': [_vehicle_block(vehicle) for vehicle in vehicles]}


def _vehicle_block(vehicle):
    payload = vehicle._vtracking_map_payload()
    return {
        'id': payload['id'],
        'name': payload['name'],
        'latitude': payload['latitude'],
        'longitude': payload['longitude'],
        'status': payload['status'],
        'status_label': payload['status_label'],
        'speed': payload['speed'],
        'geocoding': payload.get('geocoding') or '',
        'position_at': payload['position_at'],
        'is_stale': payload['is_stale'],
        'driver_name': payload['driver_name'],
    }


def _plan_block(plan, my_order_ids):
    """Một chuyến, gọn cho người bán hàng đọc. Điểm nào có đơn của họ thì đánh dấu ``mine``."""
    stops = [_stop_block(line, my_order_ids) for line in plan['lines']]
    return {
        'id': plan['id'],
        'vehicle_plate': plan['vehicle_plate'],
        'driver_name': plan['driver_name'],
        'session_label': plan['session_label'],
        'state': plan['state'],
        'zone_name': plan['zone_name'],
        'stop_count': plan['stop_count'],
        'line_count': plan['line_count'],
        'distance_km': plan['distance_km'],
        'duration_display': plan['duration_display'],
        'start_name': (plan.get('start') or {}).get('name'),
        'delivered_count': sum(1 for stop in stops if stop['delivered']),
        'has_mine': any(stop['mine'] for stop in stops),
        'stops': stops,
    }


def _stop_block(line, my_order_ids):
    return {
        'sequence': line['sequence'],
        'reference': line['display_reference'],
        'partner_name': line['partner_name'],
        'address': line['address'],
        'zone_name': line['zone_name'],
        'delivered': line['delivered'],
        'returned': line['returned'],
        'waiting_picking': line['waiting_picking'],
        'procedure_blocked': line['procedure_blocked'],
        'arrive_offset_minutes': line.get('arrive_offset_minutes'),
        'mine': line['sale_order_id'] in my_order_ids,
    }


def _my_order_ids(env):
    """Id đơn bán do chính người đang xem phụ trách. Dùng để tô điểm trên bảng chuyến."""
    return env['sale.order'].sudo().search([
        ('user_id', '=', env.user.id),
        ('state', 'in', ('sale', 'done')),
    ]).ids


def my_unplanned_orders(env):
    """Đơn của tôi còn phải giao mà CHƯA nằm trong kế hoạch nào.

    Đây là chỗ người bán hàng bấm "Nhờ AI xếp lịch" — nên chỉ liệt kê đơn thật sự còn phải
    giao, sắp theo ngày hẹn gần nhất trước.
    """
    today = fields.Date.context_today(env['sale.order'])
    orders = env['sale.order'].sudo().search([
        ('user_id', '=', env.user.id),
        ('state', 'in', ('sale', 'done')),
        ('delivery_status', '!=', 'full'),
        ('vtracking_plan_id', '=', False),
        '|', ('commitment_date', '=', False),
        ('commitment_date', '<=', fields.Date.add(today, days=UNPLANNED_HORIZON_DAYS)),
    ], order='commitment_date asc, id desc', limit=MAX_UNPLANNED)
    # Đơn được xếp theo PHIẾU XUẤT thì ``vtracking_plan_id`` trên đơn vẫn trống — phải hỏi
    # thêm dòng kế hoạch, nếu không đơn đã có chuyến vẫn hiện ra là "chưa xếp".
    lines = env['hlv.vtracking.plan.line'].sudo().search([
        '|', ('sale_order_id', 'in', orders.ids), ('picking_id.sale_id', 'in', orders.ids),
    ])
    planned_ids = set(lines.mapped('sale_order_id').ids) | set(
        lines.mapped('picking_id.sale_id').ids)
    return [{
        'id': order.id,
        'name': order.name,
        'partner_name': order.partner_id.display_name,
        'commitment_date': fields.Datetime.to_string(order.commitment_date)
        if order.commitment_date else None,
        'delivery_status': order.delivery_status or '',
        'amount_total': order.amount_total,
    } for order in orders if order.id not in planned_ids]


def my_requests(env):
    """Yêu cầu tôi đã gửi AI, mới nhất trước — kèm câu trả lời để đọc ngay trên trang."""
    requests = env['hlv.vtracking.ai.request'].sudo().search([
        ('requester_id', '=', env.user.id),
    ], limit=MAX_MY_REQUESTS)
    labels = dict(requests._fields['request_type'].selection)
    verdicts = dict(requests._fields['verdict'].selection)
    states = dict(requests._fields['state'].selection)
    return [{
        'id': record.id,
        'created_at': fields.Datetime.to_string(record.create_date),
        'type_label': labels.get(record.request_type, ''),
        'state': record.state,
        'state_label': states.get(record.state, ''),
        'open': record.state in OPEN_STATES,
        'order_name': record.sale_order_id.name or record.picking_id.name or '',
        'message': record.message,
        'verdict': record.verdict or None,
        'verdict_label': verdicts.get(record.verdict, ''),
        'answer': record.answer or '',
    } for record in requests]


def create_request(env, values):
    """Tạo phiếu yêu cầu từ trang sale. Trả về danh sách yêu cầu đã cập nhật.

    Không nhận ``requester_id`` từ trình duyệt: người gửi luôn là người đang đăng nhập.
    """
    Request = env['hlv.vtracking.ai.request'].sudo()
    Request.create({
        'requester_id': env.user.id,
        'company_id': env.company.id,
        'request_type': values['request_type'],
        'message': values['message'],
        'sale_order_id': values.get('sale_order_id') or False,
        'plan_id': values.get('plan_id') or False,
        'desired_date': values.get('desired_date') or False,
        'desired_session': values.get('desired_session') or False,
    })
    return {'my_requests': my_requests(env)}
