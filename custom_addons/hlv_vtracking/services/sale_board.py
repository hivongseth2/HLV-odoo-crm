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
from .ai.order_service import order_line_block

# Số ngày nhìn tới trước trong ô "đơn của tôi chưa xếp". Xa hơn nữa thì chưa ai xếp chuyến,
# liệt kê ra chỉ làm nhiễu.
UNPLANNED_HORIZON_DAYS = 14
MAX_UNPLANNED = 40
MAX_MY_REQUESTS = 15


def board_data(env, day=None, saler_code=None, search=None):
    """Toàn bộ dữ liệu một lần vẽ trang: chuyến trong ngày, xe, đơn của tôi, yêu cầu của tôi.

    ``saler_code``: nhiều nhân viên dùng CHUNG một tài khoản Odoo, nên "của tôi" không suy
    được từ tài khoản. Người xem tự chọn mã sale MISA của mình trên trang; rỗng nghĩa là
    lấy toàn bộ mã đã khai cho tài khoản.
    """
    day = day or fields.Date.context_today(env['hlv.vtracking.plan'])
    company = env.company
    vehicles = env['fleet.vehicle'].sudo().search([
        ('vtracking_enabled', '=', True),
        ('company_id', 'in', [company.id, False]),
    ], order='license_plate')
    my_order_ids = set(_my_order_ids(env, saler_code))
    plans = env['hlv.vtracking.plan'].sudo().search([
        ('vehicle_id', 'in', vehicles.ids),
        ('date', '=', day),
        ('state', '!=', 'cancelled'),
    ], order='vehicle_id, session')

    return {
        'date': fields.Date.to_string(day),
        'today': fields.Date.to_string(fields.Date.context_today(env['hlv.vtracking.plan'])),
        'user_name': env.user.name,
        'tile_url': company.vtracking_map_tile_url or '',
        'tile_attribution': company.vtracking_map_attribution or '',
        'vehicles': [_vehicle_block(vehicle) for vehicle in vehicles],
        'plans': [_plan_block(plan, my_order_ids) for plan in plans],
        'my_unplanned': my_unplanned_orders(env, saler_code, search),
        'my_requests': my_requests(env),
        'saler_codes': saler_code_options(env),
        'saler_code': saler_code or '',
        # Chưa khai mã sale MISA thì không đơn nào tính là "của tôi" — trang phải nói ra,
        # nếu không người dùng tưởng mình không có đơn nào.
        'mine_configured': _mine_domain(env, saler_code) is not None,
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
    """Một chuyến, gọn cho người bán hàng đọc. Điểm nào có đơn của họ thì đánh dấu ``mine``.

    ``with_legs=True`` để có giờ tới ước tính từng điểm — đó chính là thứ người bán hàng
    cần khi khách hỏi "mấy giờ xe tới".
    """
    summary = plan_payload.plan_summary(plan)
    stops = [_stop_block(line, my_order_ids)
             for line in plan_payload.plan_lines(plan, with_legs=True)]
    return {
        'id': summary['id'],
        'vehicle_plate': summary['vehicle_plate'],
        'driver_name': summary['driver_name'],
        'session': summary['session'],
        'session_label': summary['session_label'],
        'state': summary['state'],
        'zone_name': summary['zone_name'],
        'stop_count': summary['stop_count'],
        'line_count': summary['line_count'],
        'distance_km': summary['distance_km'],
        'duration_display': summary['duration_display'],
        'start_name': (summary.get('start') or {}).get('name'),
        'start': _coords(summary.get('start') or {}),
        'delivered_count': sum(1 for stop in stops if stop['delivered']),
        'has_mine': any(stop['mine'] for stop in stops),
        'stops': stops,
    }


def _stop_block(line, my_order_ids):
    return {
        'sequence': line['seq_no'],
        'reference': line['reference'],
        'partner_name': line['partner_name'],
        'address': line['address'],
        'zone_name': line['zone_name'],
        'delivered': line['delivered'],
        'returned': line['returned'],
        'waiting_picking': line['waiting_picking'],
        'procedure_blocked': line['procedure_blocked'],
        'arrive_offset_minutes': line.get('arrive_offset_minutes'),
        'sale_order_id': line['sale_order_id'],
        'sale_order_name': line['sale_order_name'],
        'picking_id': line['picking_id'],
        'picking_name': line['picking_name'],
        'latitude': line['latitude'],
        'longitude': line['longitude'],
        'mine': line['sale_order_id'] in my_order_ids,
    }


def _coords(block):
    """Chỉ toạ độ của điểm xuất phát, hoặc None — trang dùng để vẽ lộ trình."""
    if not block or not block.get('latitude'):
        return None
    return {'latitude': block['latitude'], 'longitude': block['longitude'],
            'name': block.get('name') or ''}


def saler_code_options(env):
    """Các mã sale MISA chọn được trên trang.

    Ưu tiên mã đã khai cho tài khoản. Tài khoản dùng chung thường chưa khai gì, nên lùi về
    các mã ĐANG có trên đơn còn phải giao — người bán hàng nhận ra mã của mình trong đó.
    """
    Order = env['sale.order']
    if 'x_studio_misa_saler_code' not in Order._fields:
        return []
    configured = _configured_codes(env)
    if configured:
        return configured
    groups = Order.sudo()._read_group(
        [('state', 'in', ('sale', 'done')), ('delivery_status', '!=', 'full')],
        ['x_studio_misa_saler_code'], ['__count'],
    )
    return sorted({(code or '').strip() for code, _count in groups if (code or '').strip()})


def _configured_codes(env):
    """Mã khai sẵn cho tài khoản (nếu bản cài có trang /sale_plan)."""
    service_name = 'hlv.delivery.planner.service'
    if service_name not in env:
        return []
    return env[service_name]._get_current_user_misa_codes()


def _mine_domain(env, saler_code=None):
    """Domain "đơn của tôi" — THEO MÃ SALE MISA, không theo người tạo đơn.

    Nhiều nhân viên dùng chung một tài khoản Odoo, nên ``user_id`` không nói được đơn của
    ai. Trang /sale_plan đã có đúng luật này (mã khai trên tài khoản, kèm tuỳ chọn ôm đơn
    không có mã như đơn Shopee) — gọi lại hàm đó thay vì chép luật sang đây.

    Trả về None khi tài khoản chưa khai mã nào: giống /sale_plan, coi như KHÔNG đơn nào là
    của mình, thay vì mở ra tất cả.
    """
    if saler_code:
        # Người xem tự khai mình là ai — đây mới là thứ dùng được khi cả phòng chung một
        # tài khoản Odoo.
        return [('x_studio_misa_saler_code', '=ilike', saler_code)]
    service_name = 'hlv.delivery.planner.service'
    if service_name not in env:
        # Bản cài không có module trang sale: lùi về người phụ trách đơn.
        return [('user_id', '=', env.user.id)]
    # Không sudo: hàm bên đó đọc ``self.env.user`` để lấy mã của CHÍNH người đang xem.
    return env[service_name]._get_mine_only_domain()


def _my_order_ids(env, saler_code=None):
    """Id đơn bán thuộc về người đang xem. Dùng để tô điểm trên bảng chuyến."""
    domain = _mine_domain(env, saler_code)
    if domain is None:
        return []
    return env['sale.order'].sudo().search(
        domain + [('state', 'in', ('sale', 'done'))]).ids


def my_unplanned_orders(env, saler_code=None, search=None):
    """Đơn của tôi còn phải giao mà CHƯA nằm trong kế hoạch nào.

    Đây là chỗ người bán hàng bấm "Nhờ AI xếp lịch" — nên chỉ liệt kê đơn thật sự còn phải
    giao, sắp theo ngày hẹn gần nhất trước.
    """
    domain = _mine_domain(env, saler_code)
    if domain is None:
        return []
    if search:
        # Tìm cả theo phiếu xuất: người bán hàng hay cầm số phiếu kho đọc lên, không phải
        # lúc nào cũng nhớ số đơn.
        domain = domain + ['|', '|',
                           ('name', 'ilike', search),
                           ('partner_id.name', 'ilike', search),
                           ('picking_ids.name', 'ilike', search)]
    today = fields.Date.context_today(env['sale.order'])
    orders = env['sale.order'].sudo().search(domain + [
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


# ----------------------------------------------------------------------
# Xem nhanh một chứng từ
# ----------------------------------------------------------------------
MAX_DETAIL_LINES = 60


def document_detail(env, kind, record_id):
    """Đơn bán hoặc phiếu kho, gọn đủ để người bán hàng trả lời khách ngay.

    Cố tình KHÔNG dùng ``order_service.order_detail``: bản đó dựng cho AI nên kéo theo đơn
    mua, chuỗi kho, cụm tuyến và cả chatter — nặng và thừa với người chỉ muốn biết "đơn này
    gồm gì, giao tới đâu chưa".
    """
    if kind == 'order':
        return _order_detail(env['sale.order'].sudo().browse(int(record_id)).exists())
    return _picking_detail(env['stock.picking'].sudo().browse(int(record_id)).exists())


def _order_detail(order):
    if not order:
        return {'error': 'Không tìm thấy đơn hàng.'}
    return {
        'kind': 'order',
        'title': order.name,
        'partner_name': order.partner_id.display_name,
        'state_label': dict(order._fields['state'].selection).get(order.state, order.state),
        'delivery_status': order.delivery_status or '',
        'date_order': fields.Datetime.to_string(order.date_order) if order.date_order else None,
        'commitment_date': fields.Datetime.to_string(order.commitment_date)
        if order.commitment_date else None,
        'amount_total': order.amount_total,
        'saler_code': getattr(order, 'x_studio_misa_saler_code', '') or '',
        'address': order._vtracking_delivery_address(),
        # Dòng hàng dựng bằng đúng hàm mà API cho AI dùng — một chỗ đổi, hai nơi khớp.
        'lines': [order_line_block(line) for line in order.order_line[:MAX_DETAIL_LINES]
                  if not line.display_type],
        'pickings': [{
            'id': picking.id,
            'name': picking.name,
            'state_label': dict(picking._fields['state'].selection).get(picking.state, picking.state),
            'scheduled_date': fields.Datetime.to_string(picking.scheduled_date)
            if picking.scheduled_date else None,
        } for picking in order.picking_ids],
    }


def _picking_detail(picking):
    if not picking:
        return {'error': 'Không tìm thấy phiếu kho.'}
    return {
        'kind': 'picking',
        'title': picking.name,
        'partner_name': picking.partner_id.display_name or '',
        'state_label': dict(picking._fields['state'].selection).get(picking.state, picking.state),
        'origin': picking.origin or '',
        'scheduled_date': fields.Datetime.to_string(picking.scheduled_date)
        if picking.scheduled_date else None,
        'date_done': fields.Datetime.to_string(picking.date_done) if picking.date_done else None,
        'address': picking._vtracking_delivery_address(),
        'sale_order_id': picking.sale_id.id or None,
        'sale_order_name': picking.sale_id.name or '',
        'lines': [{
            'product': move.product_id.display_name,
            'uom': move.product_uom.name or '',
            'qty_ordered': move.product_uom_qty,
            'qty_delivered': move.quantity,
        } for move in picking.move_ids[:MAX_DETAIL_LINES] if move.state != 'cancel'],
    }
