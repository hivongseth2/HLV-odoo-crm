# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .payment_utils import PAID_TOLERANCE


class VendorDebtPayment(models.Model):
    """Một lần chi trả công nợ cho NCC — một khoản tiền trả cho nhiều đơn mua, kế toán đã làm trên MISA. Odoo chỉ ghi
    nhận (không đẩy MISA) để số "đã chi" của từng đơn và tab Tài chính của NCC đúng, và có chỗ gắn UNC.
    Tạo là tính đã chi ngay; sai thì huỷ (giữ lại dấu vết) rồi tạo phiếu mới, không sửa."""

    _name = "hlv.vendor.debt.payment"
    _description = "Thanh toán công nợ NCC"
    _order = "payment_date desc, id desc"

    name = fields.Char(string="Số phiếu", required=True, default="/", copy=False, readonly=True, index=True)
    partner_id = fields.Many2one("res.partner", string="NCC", required=True, index=True)
    company_id = fields.Many2one("res.company", string="Công ty", required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    amount = fields.Monetary(string="Số tiền", required=True)
    payment_date = fields.Date(string="Ngày chi", required=True, default=fields.Date.context_today)
    # Cùng khoá với amis.payment.request.payment_method — template trang NCC đọc chung một kiểu.
    payment_method = fields.Selection([("bank", "Chuyển khoản"), ("cash", "Tiền mặt")], string="Hình thức",
                                      required=True, default="bank")
    memo = fields.Text(string="Diễn giải")
    state = fields.Selection([("done", "Đã chi"), ("cancelled", "Đã huỷ")], string="Trạng thái", required=True,
                             default="done", index=True)
    line_ids = fields.One2many("hlv.vendor.debt.payment.line", "payment_id", string="Phân bổ vào đơn mua")
    allocated_amount = fields.Monetary(string="Đã phân bổ", compute="_compute_allocation")
    unallocated_amount = fields.Monetary(string="Chưa phân bổ", compute="_compute_allocation")
    hlv_document_ids = fields.One2many("hlv.payment.document", "debt_payment_id", string="Chứng từ chi")
    # "misa": tự ghi từ hoá đơn đã thanh toán trên MISA (hlv.misa.purchase.invoice) — kế toán không nhập tay.
    source = fields.Selection([("manual", "Nhập tay"), ("misa", "Hoá đơn MISA")], string="Nguồn", required=True,
                              default="manual", index=True)
    hlv_misa_invoice_ids = fields.One2many("hlv.misa.purchase.invoice", "debt_payment_id", string="Hoá đơn MISA")

    _sql_constraints = [
        ("amount_positive", "CHECK(amount > 0)", "Số tiền phiếu thanh toán công nợ phải lớn hơn 0."),
    ]

    @api.depends("amount", "line_ids.amount")
    def _compute_allocation(self):
        for payment in self:
            payment.allocated_amount = sum(payment.line_ids.mapped("amount"))
            payment.unallocated_amount = payment.amount - payment.allocated_amount

    @api.constrains("partner_id", "amount", "line_ids")
    def _check_allocation(self):
        # Chặn cứng ở model những gì không bao giờ đúng; "trả một phần / còn dư" chỉ là cảnh báo ở trang kế toán.
        for payment in self:
            vendor = payment.partner_id.commercial_partner_id
            foreign = payment.line_ids.purchase_order_id.filtered(lambda o: o.partner_id.commercial_partner_id != vendor)
            if foreign:
                raise ValidationError(_("Đơn %s không phải của NCC %s.") % (", ".join(foreign.mapped("name")), vendor.name))
            if payment.allocated_amount > payment.amount + PAID_TOLERANCE:
                raise ValidationError(_("Tổng phân bổ vượt số tiền phiếu %s.") % payment.name)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("hlv.vendor.debt.payment") or "/"
        return super().create(vals_list)

    def action_cancel(self):
        self.write({"state": "cancelled"})

    # Cùng tên hàm với amis.payment.request (models/payment_request.py) — template tab Tài chính đọc chung hai loại.
    def _hlv_is_paid(self):
        self.ensure_one()
        return self.state == "done"

    def _hlv_vendor_label(self):
        self.ensure_one()
        return "Đã chi" if self._hlv_is_paid() else "Đã huỷ"

    def _hlv_vendor_documents(self):
        self.ensure_one()
        return self.hlv_document_ids.filtered("visible_to_vendor")

    def _hlv_orders(self):
        """Các đơn mua phiếu này trả."""
        self.ensure_one()
        return self.line_ids.purchase_order_id

