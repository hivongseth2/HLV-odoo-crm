"""Xem nhanh MỘT chứng từ từ trang `/giao-hang`: đơn bán, hoặc phiếu xuất kho của một điểm.

Phiếu xuất kho là thứ người bán hàng cần nhất khi khách gọi hỏi, nên nó được dựng kỹ hơn
đơn bán: bốn mốc của phiếu, chuyến đang chở nó, và bảng ba cột *đơn đặt / phiếu này chở /
còn lại chờ phiếu sau* — câu hỏi "đợt này khách nhận được bao nhiêu" chỉ trả lời được khi
thấy cả ba con số cạnh nhau.

Không bịa mốc thời gian: mốc nào Odoo không lưu giờ thì trả ``at = None`` và trang hiện
"chưa" thay vì đoán.
"""

from odoo import fields

from .ai.order_service import order_line_block

MAX_DETAIL_LINES = 60


def document_detail(env, kind, record_id):
    if kind == 'order':
        return order_detail(env['sale.order'].sudo().browse(int(record_id)).exists())
    return picking_detail(env['stock.picking'].sudo().browse(int(record_id)).exists())


def order_detail(order):
    if not order:
        return {'error': 'Không tìm thấy đơn hàng.'}
    return {
        'kind': 'order',
        'id': order.id,
        'title': order.name,
        'partner_name': order.partner_id.display_name,
        'state_label': dict(order._fields['state'].selection).get(order.state, order.state),
        'delivery_status': _delivery_status_label(order),
        'date_order': _stamp(order.date_order),
        'commitment_date': _stamp(order.commitment_date),
        'amount_total': order.amount_total,
        'saler_code': getattr(order, 'x_studio_misa_saler_code', '') or '',
        'address': order._vtracking_delivery_address(),
        'lines': [order_line_block(line) for line in order.order_line[:MAX_DETAIL_LINES]
                  if not line.display_type],
        # Chỉ phiếu XUẤT: phiếu lấy hàng và đóng gói là việc nội bộ của kho, người bán
        # hàng nhìn vào chỉ thêm rối vì ba mã cho cùng một lần giao.
        'pickings': [_picking_chip(picking) for picking in order.picking_ids
                     if picking.picking_type_code == 'outgoing'],
    }


def picking_detail(picking):
    if not picking:
        return {'error': 'Không tìm thấy phiếu kho.'}
    order = picking.sale_id
    return {
        'kind': 'picking',
        'id': picking.id,
        'title': picking.name,
        'state_label': dict(picking._fields['state'].selection).get(picking.state, picking.state),
        'partner_name': picking.partner_id.display_name or '',
        'address': picking._vtracking_delivery_address(),
        'sale_order_id': order.id or None,
        'sale_order_name': order.name or '',
        'commitment_date': _stamp(order.commitment_date) if order else None,
        'amount_total': order.amount_total if order else 0.0,
        'delivery_status': _delivery_status_label(order) if order else '',
        'milestones': _milestones(picking),
        'plan': _plan_context(picking),
        'lines': _picking_lines(picking),
        'other_pickings': [_picking_chip(other) for other in picking.sale_id.picking_ids
                           if other.id != picking.id and other.picking_type_code == 'outgoing'],
    }


def _milestones(picking):
    """Bốn mốc đời một phiếu xuất. ``at`` None = Odoo không lưu giờ cho mốc đó.

    "Đủ hàng" chỉ có trạng thái chứ không có dấu thời gian trong Odoo, nên nó luôn trả giờ
    rỗng — thà để trống còn hơn lấy ``write_date`` rồi hiện ra một con số sai.
    """
    ready = picking.state in ('assigned', 'done')
    loaded = bool(picking.shipper_receive_time)
    delivered = picking.state == 'done' and bool(picking.date_done)
    return [
        {'label': 'Có phiếu', 'done': True, 'at': _stamp(picking.create_date)},
        {'label': 'Đủ hàng', 'done': ready, 'at': None},
        {'label': 'Lên xe', 'done': loaded, 'at': _stamp(picking.shipper_receive_time)},
        {'label': 'Đã giao', 'done': delivered, 'at': _stamp(picking.date_done) if delivered else None},
    ]


def _plan_context(picking):
    """Chuyến đang chở phiếu này: xe, phiếu là điểm thứ mấy, chuyến đi được bao nhiêu."""
    line = picking.env['hlv.vtracking.plan.line'].sudo().search(
        [('picking_id', '=', picking.id)], limit=1)
    if not line:
        return None
    plan = line.plan_id
    ordered = plan._ordered_lines()
    total = len(ordered)
    index = list(ordered).index(line) + 1 if line in ordered else 0
    delivered = len([item for item in ordered if item.delivered])
    return {
        'plan_id': plan.id,
        'vehicle_plate': plan.vehicle_id.license_plate or '',
        'session_label': dict(plan._fields['session'].selection).get(plan.session, ''),
        'stop_index': index,
        'stop_count': total,
        'delivered_count': delivered,
        'percent': round(delivered * 100.0 / total) if total else 0,
        'duration_display': plan.duration_display or '',
        'started_at': _stamp(plan.actual_start_at),
    }


def _picking_lines(picking):
    """Ba con số mỗi mặt hàng: đơn đặt bao nhiêu, phiếu này chở bao nhiêu, còn lại bao nhiêu.

    "Còn lại" tính theo ĐƠN (đặt trừ đã giao trừ phần phiếu này đang chở), nên phiếu giao
    một phần thì người bán hàng thấy ngay khách còn thiếu gì — đó là câu hỏi họ bị hỏi
    nhiều nhất.
    """
    rows = []
    for move in picking.move_ids[:MAX_DETAIL_LINES]:
        if move.state == 'cancel':
            continue
        sale_line = move.sale_line_id
        ordered = sale_line.product_uom_qty if sale_line else move.product_uom_qty
        delivered = sale_line.qty_delivered if sale_line else 0.0
        this_trip = move.product_uom_qty
        remaining = ordered - delivered - (this_trip if move.state != 'done' else 0.0)
        rows.append({
            'code': move.product_id.default_code or '',
            'product': move.product_id.name or move.description_picking or '',
            'uom': move.product_uom.name or '',
            'qty_ordered': ordered,
            'qty_this': this_trip,
            'qty_remaining': max(remaining, 0.0),
        })
    return rows


def _picking_chip(picking):
    """Một phiếu khác của cùng đơn, đủ để nhận ra nó đã đi chuyến nào, xong chưa."""
    line = picking.env['hlv.vtracking.plan.line'].sudo().search(
        [('picking_id', '=', picking.id)], limit=1)
    return {
        'id': picking.id,
        'name': picking.name,
        'state': picking.state,
        'state_label': dict(picking._fields['state'].selection).get(picking.state, picking.state),
        'date_done': _stamp(picking.date_done),
        'vehicle_plate': line.plan_id.vehicle_id.license_plate or '' if line else '',
    }


def _delivery_status_label(order):
    field = order._fields.get('delivery_status')
    selection = dict(field.selection) if field and field.type == 'selection' else {}
    return selection.get(order.delivery_status, order.delivery_status or '')


def _stamp(value):
    return fields.Datetime.to_string(value) if value else None
