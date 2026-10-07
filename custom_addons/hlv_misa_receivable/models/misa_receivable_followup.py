# -*- coding: utf-8 -*-
from odoo import fields, models


class MisaReceivableFollowup(models.Model):
    """Phần sale tự nhập khi đi đòi nợ 1 hóa đơn (cột "Ngày thu nợ", "Xác suất thu" của sheet
    công nợ). Tách khỏi misa.sale.payment.line vì dòng đó bị xóa/tạo lại mỗi lần tra MISA."""
    _name = 'misa.receivable.followup'
    _description = 'Theo dõi thu nợ theo hóa đơn MISA'
    _rec_name = 'invoice_no'

    invoice_no = fields.Char(string='Số hóa đơn', required=True)
    # Khóa thật: số hóa đơn có thể trùng giữa 2 ký hiệu (xem misa_receivable_utils.invoice_identity).
    invoice_key = fields.Char(string='Mã nhận diện hóa đơn', index=True)
    promise_date = fields.Date(string='Ngày hẹn thu')
    collect_rate = fields.Integer(string='Xác suất thu (%)')
    note = fields.Char(string='Ghi chú thu nợ')

    _sql_constraints = [
        ('invoice_key_unique', 'unique(invoice_key)', 'Mỗi hóa đơn chỉ có 1 dòng theo dõi thu nợ.'),
        ('collect_rate_range', 'CHECK(collect_rate >= 0 AND collect_rate <= 100)', 'Xác suất thu phải từ 0 đến 100.'),
    ]
