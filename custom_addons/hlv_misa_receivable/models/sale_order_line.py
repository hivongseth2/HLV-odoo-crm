# -*- coding: utf-8 -*-
from odoo import api, fields, models

from odoo.addons.misa_invoice_status_report.models.stock_picking import MISA_INVOICE_AMOUNT_TOLERANCE

from .misa_receivable_utils import line_payment_state, normalize_code


class SaleOrderLineMisaPayment(models.Model):
    _inherit = 'sale.order.line'

    misa_payment_line_ids = fields.One2many('misa.sale.payment.line', 'sale_line_id', string='Chứng từ MISA')
    misa_invoiced_amount = fields.Float(
        string='Tiền đã lên chứng từ MISA', compute='_compute_misa_payment', store=True,
    )
    misa_paid_amount = fields.Float(string='Tiền đã thu (MISA)', compute='_compute_misa_payment', store=True)
    misa_unpaid_amount = fields.Float(string='Tiền chưa thu (MISA)', compute='_compute_misa_payment', store=True)
    misa_invoice_nos = fields.Char(string='Số hóa đơn MISA', compute='_compute_misa_payment', store=True)
    misa_payment_state = fields.Selection([
        ('none', 'Chưa có trên chứng từ MISA'),
        ('unpaid', 'Chưa thu'),
        ('partial', 'Thu một phần'),
        ('paid', 'Đã thu'),
        ('unknown', 'Không rõ'),
    ], string='Thu tiền (MISA)', compute='_compute_misa_payment', store=True, index=True)

    @api.depends('misa_payment_line_ids.amount', 'misa_payment_line_ids.paid_state', 'misa_payment_line_ids.invoice_no')
    def _compute_misa_payment(self):
        for line in self:
            parts = line.misa_payment_line_ids
            entries = [{'amount': part.amount, 'paid_state': part.paid_state} for part in parts]
            invoiced = sum(entry['amount'] for entry in entries)
            paid = sum(entry['amount'] for entry in entries if entry['paid_state'] == 'paid')
            line.misa_invoiced_amount = invoiced
            line.misa_paid_amount = paid
            line.misa_unpaid_amount = invoiced - paid
            line.misa_invoice_nos = ', '.join(dict.fromkeys(parts.mapped('invoice_no'))) or False
            line.misa_payment_state = line_payment_state(entries, MISA_INVOICE_AMOUNT_TOLERANCE)

    def _misa_payment_candidate(self):
        """Mô tả dòng đơn này cho allocate_entries: mã hàng, mã các sản phẩm con nếu là combo/kit
        (lấy từ chính các move Odoo đã nổ ra khi giao — đúng thứ MISA ghi trên hóa đơn), sức chứa
        là số lượng đã giao (chưa giao gì thì lấy số đặt)."""
        self.ensure_one()
        components = self.move_ids.product_id - self.product_id
        return {
            'sale_line_id': self.id,
            'code': normalize_code(self.product_id.default_code),
            'component_codes': {normalize_code(p.default_code) for p in components if p.default_code},
            'capacity': self.qty_delivered or self.product_uom_qty,
        }
