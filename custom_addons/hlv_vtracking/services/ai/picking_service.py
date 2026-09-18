"""Phiếu kho dưới góc nhìn người lập kế hoạch: phiếu xuất nào xếp lên xe được ngay, và
một phiếu cụ thể chứa những gì.
"""

from .. import plan_documents
from . import chatter_service
from .fulfillment_service import STEP_LABELS, picking_step
from .order_service import cached_coords
from .serialize import iso_datetime, partner_block, plain_text

DEFAULT_LIMIT = 100
MAX_LIMIT = 300


def ready_domain(env, company, params):
    """Phiếu xếp lên xe được ngay, trong công ty của khoá API, kèm bộ lọc của bên gọi."""
    warehouse = env['stock.warehouse'].browse(int(params['warehouse_id'])) if params.get('warehouse_id') else None
    domain = [('company_id', '=', company.id)] + plan_documents.loadable_picking_domain(warehouse)
    if params.get('search'):
        term = params['search']
        domain += ['|', '|', ('name', 'ilike', term), ('origin', 'ilike', term),
                   ('partner_id.name', 'ilike', term)]
    return domain


def ready_pickings(env, company, params, limit=DEFAULT_LIMIT, offset=0):
    """Phiếu xuất xếp lên xe được NGAY, phiếu hẹn giao sớm nhất trước."""
    Picking = env['stock.picking']
    domain = ready_domain(env, company, params)
    pickings = Picking.search(domain, limit=limit, offset=offset, order='scheduled_date asc, id asc')
    return {
        'total': Picking.search_count(domain),
        'offset': offset,
        'limit': limit,
        'count': len(pickings),
        'pickings': [picking_brief(picking) for picking in pickings],
    }


def picking_brief(picking):
    """Một phiếu ở dạng tóm tắt."""
    step = picking_step(picking)
    address = picking._vtracking_delivery_address() or None
    return {
        'id': picking.id,
        'name': picking.name,
        'step': step,
        'step_label': STEP_LABELS[step],
        'state': picking.state,
        'sale_order_id': picking.sale_id.id or None,
        'sale_order': picking._vtracking_source_name() or None,
        'customer': partner_block(picking.partner_id),
        'warehouse_id': picking.picking_type_id.warehouse_id.id or None,
        'warehouse': picking.picking_type_id.warehouse_id.name or None,
        'scheduled_date': iso_datetime(picking.scheduled_date),
        'date_done': iso_datetime(picking.date_done),
        'amount': picking._vtracking_amount(),
        'address': address,
        'coords': cached_coords(picking.env, address),
        'plan_id': picking.plan_id.id or None,
        'is_backorder': bool(picking.backorder_id),
    }


def picking_detail(picking, chatter_limit=10):
    """Một phiếu đầy đủ: từng dòng hàng, kiện đã đóng, lời dặn trên phiếu."""
    detail = picking_brief(picking)
    packages = picking.move_line_ids.mapped('result_package_id')
    detail['moves'] = [{
        'product': move.product_id.display_name,
        'uom': move.product_uom.name or None,
        'qty_demand': move.product_uom_qty,
        'qty_done': move.quantity,
        'weight_kg': (move.product_id.weight * move.product_uom_qty) or None,
    } for move in picking.move_ids if move.state != 'cancel']
    detail['package_count'] = len(packages)
    detail['packages'] = packages.mapped('name')
    # `note` của phiếu là field HTML — trả văn bản thuần, AI không cần thẻ.
    detail['note'] = plain_text(picking.note, 1000) or None
    detail['chatter'] = chatter_service.record_messages(picking, limit=chatter_limit)
    return detail
