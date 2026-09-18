"""Đọc và sửa kế hoạch giao hàng cho AI.

Mọi thao tác GHI đều để lại một dòng trên chatter của kế hoạch, ghi rõ khoá API nào làm.
Người điều phối mở kế hoạch ra phải thấy được đâu là việc AI làm — nếu không, một kế
hoạch bị đổi sau lưng sẽ không ai biết hỏi ai.
"""

from odoo.exceptions import UserError

from .. import plan_documents, plan_payload, vtracking_actual
from ...tools.vtracking_route import estimate_route, format_minutes, route_params
from .order_service import cached_coords
from .serialize import iso_date

PLAN_ACTIONS = {
    'confirm': 'action_confirm',
    'back_to_draft': 'action_back_to_draft',
    'cancel': 'action_cancel',
    'done': 'action_done',
}


# ----------------------------------------------------------------------
# Đọc
# ----------------------------------------------------------------------
def list_plans(env, company, date_from, date_to, vehicle_id=None, include_cancelled=False):
    """Các kế hoạch trong khoảng ngày, mỗi cái ở dạng tóm tắt (không kèm từng điểm)."""
    domain = [('company_id', '=', company.id), ('date', '>=', date_from), ('date', '<=', date_to)]
    if vehicle_id:
        domain.append(('vehicle_id', '=', vehicle_id))
    if not include_cancelled:
        domain.append(('state', '!=', 'cancelled'))
    plans = env['hlv.vtracking.plan'].search(domain, order='date, session, vehicle_id')
    return {
        'date_from': iso_date(date_from),
        'date_to': iso_date(date_to),
        'count': len(plans),
        'plans': [plan_payload.plan_summary(plan) for plan in plans],
    }


def plan_detail(plan):
    """Một kế hoạch đầy đủ: tóm tắt + từng điểm kèm quãng đường chặng và giờ tới cộng dồn."""
    detail = plan_payload.plan_summary(plan)
    detail['note'] = plan.note or None
    detail['route_params'] = plan._route_params()
    detail['lines'] = plan_payload.plan_lines(plan, with_legs=True)
    return detail


def plan_vs_actual(plan):
    """Bảng đối chiếu kế hoạch ↔ thực tế của một chuyến, kèm phần tóm tắt kế hoạch."""
    result = plan.vs_actual()
    result['plan'] = plan_payload.plan_summary(plan)
    return result


# ----------------------------------------------------------------------
# Ghi
# ----------------------------------------------------------------------
def refresh_actual(plan, actor):
    """Đọc lại số thực tế từ phiếu giao và GPS. Không sửa kế hoạch, chỉ đọc lại thực tế."""
    vtracking_actual.fill_plan_actuals(plan)
    log_action(plan, actor, 'đọc lại số thực tế')
    return plan_vs_actual(plan)


def create_plan(env, vehicle, day, session, start_place, actor):
    """Tạo kế hoạch cho (xe, ngày, buổi), hoặc trả lại cái đã có. Trả ``(plan, created)``."""
    if not vehicle.vtracking_enabled:
        raise UserError(
            'Xe %s chưa bật "Theo dõi vTracking" nên không lập kế hoạch được.'
            % (vehicle.license_plate or vehicle.display_name)
        )
    if start_place and not (start_place.has_coords and start_place.warehouse_id):
        raise UserError(
            'Điểm xuất phát "%s" phải có toạ độ và phải gắn với một kho trong Odoo.'
            % start_place.name
        )
    plan, created = plan_documents.get_or_create_plan(env, vehicle, day, session, start_place)
    if created:
        log_action(plan, actor, 'tạo kế hoạch')
    return plan, created


def add_documents(plan, pickings, orders, actor):
    """Xếp phiếu/đơn vào kế hoạch. Luật xếp dùng chung với hộp thoại của người dùng."""
    result = plan_documents.add_documents(plan, pickings=pickings, orders=orders)
    if result['added_line_ids']:
        log_action(plan, actor, 'xếp thêm %s chứng từ' % len(result['added_line_ids']))
    return result


def remove_lines(plan, line_ids, actor):
    """Gỡ các dòng khỏi kế hoạch. Dòng không thuộc kế hoạch này bị bỏ qua, không báo lỗi
    thành công giả: trả về đúng id đã gỡ để bên gọi tự đối chiếu."""
    ensure_editable(plan)
    lines = plan.line_ids.filtered(lambda line: line.id in set(line_ids))
    removed = lines.mapped('display_reference')
    removed_ids = lines.ids
    lines.unlink()
    if removed:
        log_action(plan, actor, 'gỡ %s' % ', '.join(removed))
    return {'removed_line_ids': removed_ids}


def resequence(plan, ordered_line_ids, actor):
    """Đặt lại thứ tự ghé theo danh sách id truyền vào.

    Dòng không có trong danh sách được giữ nguyên thứ tự tương đối và dồn xuống SAU các
    dòng đã nêu — gửi thiếu một id không được làm mất điểm đó khỏi lộ trình.
    """
    ensure_editable(plan)
    known = {line.id: line for line in plan.line_ids}
    unknown = [line_id for line_id in ordered_line_ids if line_id not in known]
    if unknown:
        raise UserError('Các dòng %s không thuộc kế hoạch "%s".' % (unknown, plan.name))
    rest = [line.id for line in plan._ordered_lines() if line.id not in set(ordered_line_ids)]
    for position, line_id in enumerate(list(ordered_line_ids) + rest, start=1):
        known[line_id].sequence = position * 10
    log_action(plan, actor, 'sắp lại thứ tự ghé')
    return plan_detail(plan)


def optimize_order(plan, actor):
    """Sắp thứ tự theo kiểu "tới điểm gần nhất chưa ghé" — điểm khởi đầu, không phải tối ưu."""
    ensure_editable(plan)
    plan.action_resequence_by_distance()
    log_action(plan, actor, 'sắp thứ tự theo điểm gần nhất')
    return plan_detail(plan)


def change_state(plan, action, actor):
    """Chuyển trạng thái kế hoạch: confirm / back_to_draft / cancel / done."""
    method = PLAN_ACTIONS.get(action)
    if not method:
        raise UserError('Hành động "%s" không hợp lệ. Dùng một trong: %s.' % (
            action, ', '.join(sorted(PLAN_ACTIONS)),
        ))
    getattr(plan, method)()
    log_action(plan, actor, 'chuyển trạng thái: %s' % action)
    return plan_payload.plan_summary(plan)


def ensure_editable(plan):
    if plan.state not in ('draft', 'confirmed'):
        raise UserError(
            'Kế hoạch "%s" đang ở trạng thái %s nên không sửa được.' % (plan.name, plan.state)
        )


def log_action(plan, actor, text):
    """Ghi dấu vết thao tác API lên chatter của kế hoạch."""
    plan.message_post(body='API (%s): %s.' % (actor, text), message_type='notification')


# ----------------------------------------------------------------------
# Thử phương án — KHÔNG ghi gì
# ----------------------------------------------------------------------
def what_if(env, company, start_place, stops):
    """Ước lượng một lộ trình giả định mà không lưu gì — để AI so các phương án.

    stops: list dict, mỗi phần tử là MỘT trong: ``{"picking_id"}``, ``{"sale_order_id"}``,
    ``{"latitude", "longitude"}``, ``{"address"}``.

    Chỉ dùng toạ độ ĐÃ CÓ trong kho toạ độ, không gọi geocoder: AI thử hàng chục phương
    án, mỗi phương án tra lại toạ độ là đốt tiền. Điểm chưa có toạ độ vẫn được tính thời
    gian giao và được đánh dấu ``has_coords: false``.
    """
    params = route_params(
        company.vtracking_avg_speed_kmh, company.vtracking_minutes_per_stop,
        company.vtracking_road_factor,
    )
    start = (start_place.latitude, start_place.longitude) if start_place and start_place.has_coords else None
    resolved = [resolve_stop(env, stop) for stop in stops]
    estimate = estimate_route(start, [item['point'] for item in resolved], params)

    legs = estimate.pop('legs')
    for item, leg in zip(resolved, legs):
        item.pop('point')
        item.update(leg)
    estimate['duration_display'] = format_minutes(estimate['total_minutes'])
    estimate['route_params'] = params
    estimate['start'] = {'place_id': start_place.id, 'name': start_place.name} if start_place else None
    estimate['stops'] = resolved
    return estimate


def resolve_stop(env, stop):
    """Một điểm giả định -> dict có khoá ``point`` (tuple toạ độ hoặc None) + nhãn để đọc."""
    label, address, point = None, None, None
    if stop.get('picking_id'):
        picking = env['stock.picking'].browse(int(stop['picking_id'])).exists()
        if not picking:
            raise UserError('Không có phiếu id %s.' % stop['picking_id'])
        label, address = picking.name, picking._vtracking_delivery_address()
    elif stop.get('sale_order_id'):
        order = env['sale.order'].browse(int(stop['sale_order_id'])).exists()
        if not order:
            raise UserError('Không có đơn bán id %s.' % stop['sale_order_id'])
        label = order.name
        address = order._vtracking_delivery_address()
    elif stop.get('latitude') and stop.get('longitude'):
        point = (float(stop['latitude']), float(stop['longitude']))
        label = stop.get('label') or 'toạ độ'
    else:
        label, address = stop.get('label') or stop.get('address'), stop.get('address')

    if point is None and address:
        coords = cached_coords(env, address)
        point = (coords['latitude'], coords['longitude']) if coords else None
    return {'label': label, 'address': address, 'has_coords': bool(point), 'point': point}
