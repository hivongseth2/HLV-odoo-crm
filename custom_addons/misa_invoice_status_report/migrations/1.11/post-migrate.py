import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Chia lại tiền HĐ cho mọi đơn đã soát theo đơn hàng — bản 1.10 lấy HĐ hải quan theo mã
    đơn trên dòng hải quan, làm phiếu được khớp tay với dòng ghi mã đơn khác về 0 (case
    KBC/OUT/11284). Thuần DB, không gọi MISA (xem migrations/1.7).

    Kèm: lần thử soát (field mới) = lần soát xong đã có, để cron không soát lại ngay các đơn
    vừa soát ở bản 1.10."""
    cr.execute("""
        UPDATE sale_order SET misa_invoice_order_attempted_at = misa_invoice_order_checked_at
        WHERE misa_invoice_order_checked_at IS NOT NULL AND misa_invoice_order_attempted_at IS NULL
    """)
    env = api.Environment(cr, SUPERUSER_ID, {})
    orders = env['sale.order'].sudo().search([('misa_invoice_order_checked_at', '!=', False)])
    orders._misa_invoice_apply_order_allocation()
    _logger.info("✅ [MISA 1.11] Chia lại tiền HĐ theo đơn cho %s đơn.", len(orders))
