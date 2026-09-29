import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Trả về 'Chưa kiểm tra' các phiếu kẹt "Đã xuất HĐ" chỉ nhờ lượt khớp hải quan đã mất —
    bản cũ ghi nhận lại hóa đơn hải quan (xóa dòng cũ, cascade xóa lượt khớp) mà không cập nhật
    phiếu (case thật KBC/OUT/11284/11670/11098 kẹt HĐ 00005319, hóa đơn giờ chỉ phủ đơn khác).

    Chỉ phiếu KHÔNG có đề nghị (request_refid), không ăn theo phiếu nào và không còn lượt khớp
    hải quan nào — HĐ của nó không còn nguồn nào chứng minh. Đối soát thường (cron) sẽ tự đánh
    giá lại. Thuần DB, không gọi MISA (xem migrations/1.7)."""
    cr.execute("""
        SELECT p.id FROM stock_picking p
        WHERE p.misa_invoice_state = 'invoiced'
          AND p.misa_invoice_request_refid IS NULL
          AND p.misa_invoice_master_picking_id IS NULL
          AND NOT COALESCE(p.misa_invoice_is_shopee, FALSE)
          AND NOT EXISTS (SELECT 1 FROM misa_invoice_customs_match m WHERE m.picking_id = p.id)
    """)
    env = api.Environment(cr, SUPERUSER_ID, {})
    Picking = env['stock.picking'].sudo()
    pickings = Picking.browse([row[0] for row in cr.fetchall()])
    for picking in pickings:
        Picking._misa_invoice_customs_refresh_picking(
            picking,
            "Không còn đề nghị hay dòng hóa đơn hải quan nào phủ phiếu này (hóa đơn hải quan đã được "
            "ghi nhận lại) — trả về 'Chưa kiểm tra' để đối soát lại.",
        )
    _logger.info("✅ [MISA 1.12] Trả %s phiếu kẹt 'Đã xuất HĐ' không còn nguồn HĐ về 'Chưa kiểm tra': %s",
                 len(pickings), ', '.join(pickings.mapped('name')))
