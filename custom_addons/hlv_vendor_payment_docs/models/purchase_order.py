# -*- coding: utf-8 -*-
from odoo import api, fields, models

from odoo.addons.hlv_vendor_quotation.models.purchase_order import CONFIRMED_STATES

from .payment_request import VENDOR_PAYMENT_STATES
from .payment_utils import PAID_TOLERANCE, PAYMENT_STATUS_LABELS, payment_status


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    hlv_debt_line_ids = fields.One2many("hlv.vendor.debt.payment.line", "purchase_order_id",
                                        string="Thanh toán công nợ")

    def _hlv_vendor_payment_requests(self):
        """Đề nghị chi NCC được thấy của đơn (đọc bằng sudo — gọi từ trang NCC), mới trước."""
        self.ensure_one()
        return self.sudo().misa_payment_request_ids.filtered(
            lambda r: r.state in VENDOR_PAYMENT_STATES).sorted(lambda r: (r.payment_date, r.id), reverse=True)

    def _hlv_debt_lines(self):
        """Phần tiền các phiếu thanh toán công nợ còn hiệu lực trả vào đơn (sudo), mới trước."""
        self.ensure_one()
        return self.sudo().hlv_debt_line_ids.filtered(lambda l: l.state == "done").sorted(
            lambda l: (l.payment_id.payment_date, l.id), reverse=True)

    def _hlv_paid_amount(self):
        """Số đã chi cho đơn: đề nghị chi đã chi + phân bổ từ phiếu thanh toán công nợ."""
        self.ensure_one()
        paid_requests = sum(r.amount for r in self._hlv_vendor_payment_requests() if r._hlv_is_paid())
        return paid_requests + sum(self._hlv_debt_lines().mapped("amount"))

    def _hlv_processing_amount(self):
        """Đề nghị chi đã gửi MISA nhưng chưa duyệt chi — trả công nợ thêm vào đơn này dễ thành trả hai lần."""
        self.ensure_one()
        return sum(r.amount for r in self._hlv_vendor_payment_requests() if not r._hlv_is_paid())

    def _hlv_open_amount(self):
        """Còn nợ NCC của đơn (không âm)."""
        self.ensure_one()
        return max(self.amount_total - self._hlv_paid_amount(), 0.0)

    @api.model
    def _hlv_open_orders_of(self, vendor):
        """Đơn đã xác nhận của NCC (mọi liên hệ con) còn nợ, cũ trước — danh sách để chọn khi trả công nợ."""
        orders = self.sudo().search([("partner_id", "child_of", vendor.id), ("state", "in", CONFIRMED_STATES)],
                                    order="date_approve asc, id asc")
        return orders.filtered(lambda o: o._hlv_open_amount() > PAID_TOLERANCE)

    def _hlv_payment_summary(self):
        """Khung "Thanh toán" trên chi tiết đơn mua của NCC: {status, label, paid, total, requests, debt_lines}."""
        self.ensure_one()
        paid = self._hlv_paid_amount()
        status = payment_status(self.amount_total, paid)
        return {
            "status": status,
            "label": PAYMENT_STATUS_LABELS[status],
            "paid": paid,
            "total": self.amount_total,
            "requests": self._hlv_vendor_payment_requests(),
            "debt_lines": self._hlv_debt_lines(),
        }
