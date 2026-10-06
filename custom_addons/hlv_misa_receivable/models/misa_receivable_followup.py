# -*- coding: utf-8 -*-
from odoo import fields, models


class MisaReceivableFollowup(models.Model):
    """Phần sale tự nhập khi đi đòi nợ 1 hóa đơn (cột "Ngày thu nợ", "Xác suất thu" của sheet
    công nợ). Tách khỏi misa.sale.payment.line vì dòng đó bị xóa/tạo lại mỗi lần tra MISA."""
    _name = 'misa.receivable.followup'
    _description = 'Theo dõi thu nợ theo hóa đơn MISA'
    _rec_name = 'invoice_no'

    invoice_no = fields.Char(string='Số hóa đơn', required=True, index=True)
    promise_date = fields.Date(string='Ngày hẹn thu')
    collect_rate = fields.Integer(string='Xác suất thu (%)')
    note = fields.Char(string='Ghi chú thu nợ')

    _sql_constraints = [
        ('invoice_no_unique', 'unique(invoice_no)', 'Mỗi hóa đơn chỉ có 1 dòng theo dõi thu nợ.'),
        ('collect_rate_range', 'CHECK(collect_rate >= 0 AND collect_rate <= 100)', 'Xác suất thu phải từ 0 đến 100.'),
    ]
