# -*- coding: utf-8 -*-
from odoo import models

from .payment_request import VENDOR_PAYMENT_STATES
from .payment_utils import PAYMENT_STATUS_LABELS, payment_status


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    def _hlv_vendor_payment_requests(self):
        """Đề nghị chi NCC được thấy của đơn (đọc bằng sudo — gọi từ trang NCC), mới trước."""
        self.ensure_one()
        return self.sudo().misa_payment_request_ids.filtered(
            lambda r: r.state in VENDOR_PAYMENT_STATES).sorted(lambda r: (r.payment_date, r.id), reverse=True)

    def _hlv_paid_amount(self):
        """Số đã chi cho đơn: cộng các đề nghị chi đã chi."""
        self.ensure_one()
        return sum(r.amount for r in self._hlv_vendor_payment_requests() if r._hlv_is_paid())

    def _hlv_payment_summary(self):
        """Khung "Thanh toán" trên chi tiết đơn mua của NCC: {status, label, paid, total, requests}."""
        self.ensure_one()
        paid = self._hlv_paid_amount()
        status = payment_status(self.amount_total, paid)
        return {
            "status": status,
            "label": PAYMENT_STATUS_LABELS[status],
            "paid": paid,
            "total": self.amount_total,
            "requests": self._hlv_vendor_payment_requests(),
        }
