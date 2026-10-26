# -*- coding: utf-8 -*-
from odoo import api, fields, models

from odoo.addons.hlv_vendor_quotation.models.purchase_order import CONFIRMED_STATES
from odoo.addons.hlv_vendor_quotation.models.delivery_utils import local_day_start_utc

from .payment_request import VENDOR_PAYMENT_STATES
from .payment_utils import PAID_TOLERANCE, PAYMENT_STATUS_LABELS, ROUNDING_TOLERANCE, payment_status

# Mốc công nợ NCC (ngày, yyyy-mm-dd): đơn xác nhận TRƯỚC mốc coi như đã chi xong — không còn nợ, không vào số công nợ
# của trang NCC / trang kế toán. Công nợ cũ hơn mốc đã thanh toán trên MISA từ trước khi có tính năng này, kéo về
# chỉ làm số công nợ sai. Sửa trên trang /unc-ncc/cong-no/misa.
DEBT_CUTOFF_PARAM = "hlv_vendor_payment_docs.debt_cutoff_date"
DEFAULT_DEBT_CUTOFF = "2026-05-01"


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

    @api.model
    def _hlv_debt_cutoff(self):
        """Mốc công nợ (date). Tham số sai / trống → mặc định DEFAULT_DEBT_CUTOFF."""
        value = self.env["ir.config_parameter"].sudo().get_param(DEBT_CUTOFF_PARAM) or DEFAULT_DEBT_CUTOFF
        try:
            return fields.Date.to_date(value)
        except ValueError:
            return fields.Date.to_date(DEFAULT_DEBT_CUTOFF)

    def _hlv_debt_tracked(self):
        """Đơn có tính công nợ không: xác nhận (date_approve) từ đầu ngày mốc công nợ theo giờ VN trở đi."""
        self.ensure_one()
        return bool(self.date_approve) and self.date_approve >= self._hlv_debt_cutoff_utc()

    @api.model
    def _hlv_debt_cutoff_utc(self):
        """Đầu ngày mốc công nợ theo giờ VN, đổi ra UTC (đúng kiểu date_approve lưu) — so / tìm đơn."""
        return local_day_start_utc(self._hlv_debt_cutoff())

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
        """Còn nợ NCC của đơn. Đơn trước mốc công nợ → 0 (coi như đã chi xong); còn không quá ROUNDING_TOLERANCE
        → 0 (lệch làm tròn giữa hoá đơn MISA và đơn Odoo, không phải nợ)."""
        self.ensure_one()
        if not self._hlv_debt_tracked():
            return 0.0
        remaining = self.amount_total - self._hlv_paid_amount()
        return remaining if remaining > ROUNDING_TOLERANCE else 0.0

    def _hlv_overpaid_amount(self):
        """Đã chi vượt giá trị đơn (đề nghị chi + công nợ cùng trả một khoản) — 0 nếu không vượt."""
        self.ensure_one()
        over = self._hlv_paid_amount() - self.amount_total
        return over if over > ROUNDING_TOLERANCE else 0.0

    @api.model
    def _hlv_open_orders_of(self, vendor):
        """Đơn đã xác nhận của NCC (mọi liên hệ con) từ mốc công nợ, còn nợ, cũ trước — danh sách để chọn khi trả công
        nợ."""
        orders = self.sudo().search([("partner_id", "child_of", vendor.id), ("state", "in", CONFIRMED_STATES),
                                     ("date_approve", ">=", self._hlv_debt_cutoff_utc())],
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
