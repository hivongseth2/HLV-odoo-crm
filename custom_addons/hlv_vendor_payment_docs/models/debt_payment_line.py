# -*- coding: utf-8 -*-
from odoo import fields, models


class VendorDebtPaymentLine(models.Model):
    """Phần tiền của một phiếu thanh toán công nợ trả cho một đơn mua."""

    _name = "hlv.vendor.debt.payment.line"
    _description = "Phân bổ thanh toán công nợ NCC"
    _order = "id"

    payment_id = fields.Many2one("hlv.vendor.debt.payment", string="Phiếu", required=True, index=True, ondelete="cascade")
    # restrict: đơn đã có tiền trả vào thì không được xoá mất dấu.
    purchase_order_id = fields.Many2one("purchase.order", string="Đơn mua", required=True, index=True, ondelete="restrict")
    currency_id = fields.Many2one(related="payment_id.currency_id")
    amount = fields.Monetary(string="Số tiền", required=True)
    # Lưu để lọc dòng của phiếu còn hiệu lực ngay trên đơn mua, không phải đọc từng phiếu.
    state = fields.Selection(related="payment_id.state", store=True, index=True)

    _sql_constraints = [
        ("amount_positive", "CHECK(amount > 0)", "Số tiền phân bổ vào đơn phải lớn hơn 0."),
        ("order_unique", "UNIQUE(payment_id, purchase_order_id)", "Một đơn mua chỉ phân bổ một lần trong một phiếu."),
    ]
