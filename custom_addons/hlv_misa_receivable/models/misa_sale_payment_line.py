# -*- coding: utf-8 -*-
from odoo import fields, models

PAID_STATE_SELECTION = [
    ('unpaid', 'Chưa thu'),
    ('paid', 'Đã thu'),
    ('unknown', 'Không rõ'),
]


class MisaSalePaymentLine(models.Model):
    """1 phần của 1 dòng chứng từ bán hàng MISA đã gắn vào 1 dòng đơn bán Odoo.

    Ảnh chụp lần tra MISA gần nhất, không phải nguồn sự thật: mỗi lần tra lại 1 hóa đơn là xóa
    hết dòng của hóa đơn đó rồi tạo lại (xem stock.picking._misa_payment_scan_invoice). 1 dòng
    chứng từ có thể tách thành nhiều bản ghi khi đơn có nhiều dòng cùng mã hàng."""
    _name = 'misa.sale.payment.line'
    _description = 'Dòng chứng từ bán hàng MISA theo dòng đơn bán'
    _order = 'due_date, invoice_no, id'

    sale_line_id = fields.Many2one('sale.order.line', string='Dòng đơn bán', required=True, ondelete='cascade', index=True)
    order_id = fields.Many2one(related='sale_line_id.order_id', store=True, index=True, string='Đơn bán')
    product_id = fields.Many2one(related='sale_line_id.product_id', string='Sản phẩm')
    # Khóa tra lại = đúng chuỗi số hóa đơn lưu trên phiếu xuất kho (misa_invoice_no) — xóa/tạo lại
    # theo khóa này nên không chuẩn hóa thêm.
    invoice_no = fields.Char(string='Số hóa đơn', required=True, index=True)
    invoice_date = fields.Date(string='Ngày hóa đơn')
    due_date = fields.Date(string='Hạn thu', index=True)
    due_source = fields.Selection([
        ('payment_term', 'Theo điều khoản thanh toán của đơn'),
        ('invoice_date', 'Đơn không có điều khoản — đến hạn ngay ngày hóa đơn'),
    ], string='Cách tính hạn thu')
    voucher_refid = fields.Char(string='MISA refid chứng từ')
    voucher_refno = fields.Char(string='Số chứng từ', index=True)
    partner_code = fields.Char(string='Mã KH (MISA)')
    partner_name = fields.Char(string='Tên khách hàng (MISA)')
    saler_code = fields.Char(string='Mã sale MISA', index=True)
    item_code = fields.Char(string='Mã hàng (MISA)')
    description = fields.Char(string='Tên hàng (MISA)')
    quantity = fields.Float(string='Số lượng (MISA)')
    unit_name = fields.Char(string='ĐVT (MISA)')
    amount = fields.Float(string='Tiền có VAT')
    is_component = fields.Boolean(
        string='Mã con của combo',
        help='Dòng chứng từ ghi mã sản phẩm con, gắn vào dòng combo của đơn — số lượng là của mã con.',
    )
    paid_state = fields.Selection(PAID_STATE_SELECTION, string='Tình trạng thu', index=True)
    checked_at = fields.Datetime(string='Tra MISA lúc')
