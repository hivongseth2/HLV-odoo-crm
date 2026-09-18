"""Đơn bán dưới góc nhìn của người lập kế hoạch giao hàng.

Mỗi đơn được mô tả bằng bốn câu hỏi mà AI phải trả lời được trước khi xếp xe:
hàng đã về chưa (``supply``), kho soạn tới đâu (``fulfillment``), giao tới đâu và bằng cách
nào (``delivery``), và có ai dặn gì không (``latest_note`` / chatter).
"""

from ...tools.vtracking_address import address_key
from .. import plan_documents
from . import chatter_service, fulfillment_service, supply_service
from .serialize import (
    coords_block, iso_datetime, one_line_address, optional_field, partner_block, plain_text,
)

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

# Field Studio trên sale.order: "Hình thức giao hàng" (GỬI CPN, BOOK GRAB, KHÁCH GHÉ LẤY...).
STUDIO_DELIVERY_METHOD_FIELD = 'x_studio_htgh'


def pending_domain(env, company, params):
    """Domain các đơn CÒN PHẢI GIAO của công ty, kèm bộ lọc của bên gọi."""
    warehouse = env['stock.warehouse'].browse(int(params['warehouse_id'])) if params.get('warehouse_id') else None
    domain = [('company_id', '=', company.id)] + plan_documents.open_order_domain(warehouse)
    if params.get('search'):
        term = params['search']
        domain += ['|', ('name', 'ilike', term), ('partner_id.name', 'ilike', term)]
    if params.get('commitment_from'):
        domain.append(('commitment_date', '>=', params['commitment_from']))
    if params.get('commitment_to'):
        domain.append(('commitment_date', '<=', params['commitment_to']))
    return domain


def pending_orders(env, company, params, limit=DEFAULT_LIMIT, offset=0):
    """Danh sách đơn còn phải giao, kèm đủ thông tin để AI lọc mà không phải mở từng đơn.

    Lọc sau truy vấn (``stage``, ``unplanned_only``) được áp trên TRANG đang lấy chứ không
    trên toàn bộ: giai đoạn của đơn suy từ phiếu kho, không phải một cột để đưa vào domain.
    ``total`` vì thế là tổng đơn còn phải giao, không phải tổng sau khi lọc giai đoạn.
    """
    Order = env['sale.order']
    domain = pending_domain(env, company, params)
    orders = Order.search(domain, limit=limit, offset=offset, order='commitment_date asc, date_order asc')

    purchases = supply_service.purchases_by_order_name(env, orders.mapped('name'))
    notes = chatter_service.latest_notes(orders)
    items = [order_brief(order, purchases.get(order.name), notes.get(order.id)) for order in orders]

    if params.get('stage'):
        items = [item for item in items if item['fulfillment']['stage'] == params['stage']]
    if params.get('unplanned_only') in ('1', 'true', 'True'):
        items = [item for item in items if not item['plan']]
    return {
        'total': Order.search_count(domain),
        'offset': offset,
        'limit': limit,
        'count': len(items),
        'orders': items,
    }


def order_brief(order, purchases=None, latest_note=None):
    """Một đơn ở dạng tóm tắt — đủ để quyết định xếp hay chưa."""
    if purchases is None:
        purchases = supply_service.purchases_by_order_name(order.env, [order.name])[order.name]
    chain = fulfillment_service.delivery_chain(order)
    # Danh sách không cần từng phiếu; chi tiết đơn mới trả `steps`.
    fulfillment = {key: value for key, value in chain.items() if key != 'steps'}
    return {
        'id': order.id,
        'name': order.name,
        'customer': partner_block(order.partner_id),
        'order_date': iso_datetime(order.date_order),
        'commitment_date': iso_datetime(order.commitment_date),
        'amount_total': order.amount_total,
        'delivery_status': order.delivery_status or None,
        'warehouse_id': order.warehouse_id.id or None,
        'warehouse': order.warehouse_id.name or None,
        'delivery': delivery_block(order),
        'fulfillment': fulfillment,
        'supply': supply_service.supply_summary(purchases),
        'plan': plan_membership(order),
        'latest_note': latest_note,
    }


def order_detail(order, chatter_limit=15):
    """Toàn bộ thông tin của một đơn: dòng hàng, từng phiếu kho, từng đơn mua, hội thoại."""
    purchases = supply_service.purchases_by_order_name(order.env, [order.name])[order.name]
    detail = order_brief(order, purchases, None)
    detail['fulfillment'] = fulfillment_service.delivery_chain(order)
    detail['supply']['purchases'] = [supply_service.purchase_block(p) for p in purchases]
    detail['load'] = fulfillment_service.load_estimate(order)
    detail['salesperson'] = order.user_id.name or None
    detail['note'] = plain_text(order.note, 1000) or None
    detail['lines'] = [order_line_block(line) for line in order.order_line if not line.display_type]
    detail['chatter'] = chatter_service.record_messages(order, limit=chatter_limit)
    detail.pop('latest_note', None)
    return detail


def order_line_block(line):
    return {
        'product': line.product_id.display_name or line.name,
        'description': plain_text(line.name, 200) or None,
        'uom': line.product_uom.name or None,
        'qty_ordered': line.product_uom_qty,
        'qty_delivered': line.qty_delivered,
        'qty_remaining': max(line.product_uom_qty - line.qty_delivered, 0.0),
        'price_subtotal': line.price_subtotal,
        'weight_kg': line.product_id.weight or None,
    }


def delivery_block(order):
    """Giao tới đâu, bằng cách nào.

    ``method_note`` là ô "Hình thức giao hàng" sale gõ tay (GỬI CPN, BOOK GRAB, KHÁCH GHÉ
    LẤY HÀNG...). Đơn có ghi chú kiểu đó thường KHÔNG đi xe công ty — AI phải đọc ô này
    trước khi xếp đơn lên xe.

    Địa chỉ ưu tiên lấy từ phiếu xuất (nơi kho ghi địa chỉ thật của chuyến), chưa có
    phiếu thì lấy địa chỉ giao của đơn.
    """
    out_picking = order.picking_ids.filtered(
        lambda p: p.picking_type_id.code == 'outgoing' and p.state != 'cancel'
    )[:1]
    shipping = order.partner_shipping_id or order.partner_id
    address = (
        out_picking._vtracking_delivery_address() if out_picking else None
    ) or one_line_address(shipping)
    return {
        'address': address,
        'address_source': 'picking' if out_picking else 'order',
        'coords': cached_coords(order.env, address),
        'contact': partner_block(shipping),
        'method_note': optional_field(order, STUDIO_DELIVERY_METHOD_FIELD),
    }


def cached_coords(env, address):
    """Toạ độ ĐÃ CÓ SẴN trong kho toạ độ cho địa chỉ này, hoặc None.

    Chỉ đọc, không gọi geocoder và không tăng đếm "dùng lại": endpoint liệt kê đơn có thể
    bị gọi hàng trăm lần, không được để mỗi lần xem là một lần trả tiền tra toạ độ. Toạ độ
    mới chỉ được tra khi chứng từ thật sự được xếp vào kế hoạch.
    """
    key = address_key(address)
    if not key:
        return None
    record = env['hlv.vtracking.address'].search([
        ('address_key', '=', key), ('company_id', '=', env.company.id),
    ], limit=1)
    if not record or record.outside_vietnam:
        return None
    block = coords_block(record.latitude, record.longitude)
    if block:
        block['geo_state'] = record.geo_state
    return block


def plan_membership(order):
    """Đơn này đang nằm trong kế hoạch nào — xếp theo đơn, hoặc qua phiếu xuất của nó.

    Trả về None khi chưa xếp. Một đơn giao nhiều đợt có thể nằm ở nhiều kế hoạch, nên trả
    về danh sách.
    """
    lines = order.vtracking_plan_line_ids | order.picking_ids.mapped('plan_line_ids')
    if not lines:
        return None
    return [{
        'plan_id': line.plan_id.id,
        'plan_name': line.plan_id.name,
        'plan_state': line.plan_id.state,
        'line_id': line.id,
        'reference': line.display_reference,
    } for line in lines]
