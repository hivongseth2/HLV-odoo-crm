import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Chỉ làm việc thuần DB, KHÔNG gọi MISA (xem lý do ở migrations/1.7):

    1. Cộng lại tiền HĐ hải quan của từng phiếu từ TẤT CẢ lượt khớp đã có — bản cũ chỉ ghi
       tiền của lượt khớp đầu tiên (case KBC/OUT/12416).
    2. Tính lại misa_invoice_allocated_amount cho mọi phiếu xuất kho: công thức đổi (phiếu
       'invoiced' tiền 0 nhưng được phủ 1 phần giờ nhận phần đã khớp), mà Odoo không tự tính
       lại field đã lưu khi chỉ đổi code.

    Phần CẦN gọi MISA do cron tự làm dần sau khi deploy: cron hải quan đọc lại hóa đơn cũ để
    lấy tiền có VAT từng dòng (misa.invoice.customs.line.resync_amounts_from_misa), cron trạng
    thái kiểm lại phiếu gắn nhầm đề nghị "_1" (_misa_invoice_recheck_suffixed_requests).
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    Picking = env['stock.picking'].sudo()

    customs_pickings = env['misa.invoice.customs.match'].sudo().search([]).mapped('picking_id')
    for picking in customs_pickings:
        Picking._misa_invoice_customs_apply_to_picking(picking)
    _logger.info("✅ [MISA 1.9] Cộng lại tiền HĐ hải quan cho %s phiếu.", len(customs_pickings))

    pickings = Picking.search([('picking_type_id.code', '=', 'outgoing')])
    env.add_to_compute(Picking._fields['misa_invoice_allocated_amount'], pickings)
    Picking.flush_model(['misa_invoice_allocated_amount'])
    _logger.info("✅ [MISA 1.9] Tính lại tiền HĐ quy về phiếu cho %s phiếu.", len(pickings))
