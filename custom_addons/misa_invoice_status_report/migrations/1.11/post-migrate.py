import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Chia lại tiền HĐ cho mọi đơn đã soát theo đơn hàng — bản 1.10 lấy HĐ hải quan theo mã
    đơn trên dòng hải quan, làm phiếu được khớp tay với dòng ghi mã đơn khác về 0 (case
    KBC/OUT/11284). Thuần DB, không gọi MISA (xem migrations/1.7)."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    orders = env['sale.order'].sudo().search([('misa_invoice_order_checked_at', '!=', False)])
    orders._misa_invoice_apply_order_allocation()
    _logger.info("✅ [MISA 1.11] Chia lại tiền HĐ theo đơn cho %s đơn.", len(orders))
