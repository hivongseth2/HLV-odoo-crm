# -*- coding: utf-8 -*-
from odoo import fields, models

from .payment_request import VENDOR_PAYMENT_STATES


class VendorQuoteAccess(models.Model):
    _inherit = "hlv.vendor.quote.access"

    # Lần cuối lấy hoá đơn đã thanh toán từ MISA cho NCC này (lượt lấy cho mọi NCC — trang /unc-ncc/cong-no/misa).
    hlv_misa_synced_at = fields.Datetime(string="Lấy hoá đơn MISA lúc", readonly=True, copy=False)

    def _vendor_purchase_orders(self):
        """Thêm vào tab "Đơn mua hàng" các đơn của NCC đã được trả bằng phiếu thanh toán công nợ (kể cả đơn không lên
        từ báo giá trên link) — NCC mở được đơn mình vừa nhận tiền. Cùng luật trạng thái với các đơn khác.
        Cố ý KHÔNG mở rộng purchase.order._hlv_vendor_portal_orders: hàm đó còn quyết định gửi thông báo / nhắc giao
        trễ cho NCC — đơn cũ chỉ vì được trả tiền thì không nên bị nhắc lại."""
        orders = super()._vendor_purchase_orders()
        paid = self.env["hlv.vendor.debt.payment.line"].sudo().search([
            ("payment_id.partner_id", "=", self.partner_id.commercial_partner_id.id), ("state", "=", "done"),
        ]).purchase_order_id
        return orders | paid.filtered_domain(self.env["purchase.order"]._hlv_vendor_visible_domain())

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
