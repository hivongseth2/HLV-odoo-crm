# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.addons.hlv_vendor_quotation.models.vendor_quote_utils import format_vn_number


class AmisPaymentRequestWizard(models.TransientModel):
    _inherit = "amis.payment.request.wizard"

    hlv_debt_warning = fields.Char(string="Cảnh báo công nợ", compute="_compute_hlv_debt_warning")

    @api.depends("purchase_order_id")
    def _compute_hlv_debt_warning(self):
        # Tiền đi hai đường (đề nghị chi Odoo + thanh toán công nợ / hoá đơn MISA) — báo người lập trước khi gửi MISA.
        for wizard in self:
            order = wizard.purchase_order_id
            lines = order._hlv_debt_lines() if order else order
            wizard.hlv_debt_warning = (
                "Đơn %s đã được trả công nợ %s (%s) — còn nợ %s. Kiểm kẻo trả hai lần." % (
                    order.name, format_vn_number(round(sum(lines.mapped("amount")))),
                    ", ".join(lines.payment_id.mapped("name")), format_vn_number(round(order._hlv_open_amount())))
                if lines else False)
