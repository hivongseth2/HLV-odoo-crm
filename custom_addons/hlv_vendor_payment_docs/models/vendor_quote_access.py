# -*- coding: utf-8 -*-
from odoo import models

from .payment_request import VENDOR_PAYMENT_STATES


class VendorQuoteAccess(models.Model):
    _inherit = "hlv.vendor.quote.access"

    def _hlv_finance_records(self, orders=None):
        """Khoản chi NCC này thấy trên tab Tài chính (đọc bằng sudo): (đề nghị chi của đơn mua NCC thấy, ở trạng thái
        NCC được thấy; phiếu thanh toán công nợ còn hiệu lực của chính NCC). orders: đơn mua của NCC nếu đã tính sẵn."""
        self.ensure_one()
        orders = self._vendor_purchase_orders() if orders is None else orders
        requests = self.env["amis.payment.request"].sudo().search(
            [("purchase_order_id", "in", orders.ids), ("state", "in", VENDOR_PAYMENT_STATES)])
        debts = self.env["hlv.vendor.debt.payment"].sudo().search(
            [("partner_id", "=", self.partner_id.commercial_partner_id.id), ("state", "=", "done")])
        return requests, debts

    def _hlv_finance_count(self):
        """Số trên tab "Tài chính": số khoản chi (đề nghị chi + phiếu công nợ)."""
        requests, debts = self._hlv_finance_records()
        return len(requests) + len(debts)
