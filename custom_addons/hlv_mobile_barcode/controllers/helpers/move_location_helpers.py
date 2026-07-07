import logging
from odoo import _
from odoo.http import request

_logger = logging.getLogger(__name__)


# Bảo vệ idempotency cho move_location / move_location_batch: tránh tạo phiếu INT
# trùng nhau khi 2 RPC gần nhau (double-click, retry, hay 2 client).
MOBILE_DYN_MOVE_WINDOW_SECONDS = 10
MOBILE_DYN_MOVE_MARKER = 'HLV_MOBILE_DYN_MOVE'


def _find_recent_mobile_dyn_move_picking(source_loc, dest_loc, marker_value):
    """Trả về picking INT gần đây của cùng user khớp marker (idempotency)."""
    from datetime import datetime, timedelta
    window_start = datetime.now() - timedelta(seconds=MOBILE_DYN_MOVE_WINDOW_SECONDS)
    note_token = '{}:{}'.format(MOBILE_DYN_MOVE_MARKER, marker_value)
    candidates = request.env['stock.picking'].sudo().search([
        ('picking_type_id.code', '=', 'internal'),
        ('create_date', '>=', window_start),
        ('create_uid', '=', request.env.user.id),
        ('location_id', '=', source_loc.id),
        '|',
        ('location_dest_id', '=', dest_loc.id if dest_loc else False),
        ('note', 'like', note_token),
    ], order='id desc', limit=20)
    # Lọc chính xác theo marker trong note để tránh match nhầm picking khác.
    for picking in candidates:
        if note_token in (picking.note or ''):
            return picking
    return request.env['stock.picking'].browse()


def _build_mobile_dyn_move_marker(product, dest_loc, qty, extra=''):
    base = '{p}:{l}:{q}:{e}'.format(
        p=product.id,
        l=dest_loc.id if dest_loc else 0,
        q=qty,
        e=extra,
    )
    return base


def _lock_source_quants(product, source_loc):
    """Khóa row quants nguồn để chống 2 request đồng thời tranh quant."""
    request.env.cr.execute(
        """
            SELECT id
              FROM stock_quant
             WHERE product_id = %s
               AND location_id = %s
               AND quantity > 0
             ORDER BY id
             FOR UPDATE
        """,
        (product.id, source_loc.id),
    )