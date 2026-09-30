import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Tính lại tiền thực xuất ròng cho mọi phiếu xuất kho có hàng trả — bản cũ chỉ bắt phiếu trả
    loại 'incoming', bỏ sót phiếu trả làm bằng "Lệnh chuyển hàng nội bộ" (case thật KBC/OUT/09504
    trả toàn bộ 12.536.640 đ mà phiếu vẫn ghi đủ tiền), và định giá hàng trả theo giá dòng đơn
    hiện tại thay vì theo tiền gộp đã ghi. Thuần DB, không gọi MISA (xem migrations/1.7)."""
    cr.execute("""
        SELECT DISTINCT orig.picking_id
        FROM stock_move ret
        JOIN stock_move orig ON orig.id = ret.origin_returned_move_id
        JOIN stock_picking p ON p.id = orig.picking_id
        JOIN stock_picking_type t ON t.id = p.picking_type_id
        WHERE ret.state = 'done' AND orig.state = 'done' AND t.code = 'outgoing'
    """)
    env = api.Environment(cr, SUPERUSER_ID, {})
    pickings = env['stock.picking'].sudo().browse([row[0] for row in cr.fetchall()])
    changed = []
    for picking in pickings:
        before = picking.misa_invoice_net_actual_amount
        picking._misa_invoice_recompute_net_amount()
        if abs((picking.misa_invoice_net_actual_amount or 0.0) - (before or 0.0)) > 1.0:
            changed.append("%s: %.0f → %.0f" % (picking.name, before or 0.0, picking.misa_invoice_net_actual_amount))
    _logger.info("✅ [MISA 1.14] Tính lại tiền thực xuất cho %s phiếu có hàng trả, %s phiếu đổi số: %s",
                 len(pickings), len(changed), '; '.join(changed))
