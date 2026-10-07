# -*- coding: utf-8 -*-
from odoo import api, fields, models

from .misa_receivable_utils import invoice_identity

PAID_STATE_SELECTION = [
    ('unpaid', 'Chưa thu'),
    ('paid', 'Đã thu'),
    ('unknown', 'Không rõ'),
]


class MisaSalePaymentLine(models.Model):
    """1 phần của 1 dòng chứng từ bán hàng MISA đã gắn vào 1 dòng đơn bán Odoo.

    Ảnh chụp lần tra MISA gần nhất, không phải nguồn sự thật: mỗi lần tra lại 1 hóa đơn thì cập
    nhật tại chỗ theo kết quả mới (xem stock.picking._misa_payment_store). 1 dòng
    chứng từ có thể tách thành nhiều bản ghi khi đơn có nhiều dòng cùng mã hàng."""
    _name = 'misa.sale.payment.line'
    _description = 'Dòng chứng từ bán hàng MISA theo dòng đơn bán'
    _order = 'due_date, invoice_no, id'

    sale_line_id = fields.Many2one('sale.order.line', string='Dòng đơn bán', required=True, ondelete='cascade', index=True)
    order_id = fields.Many2one(related='sale_line_id.order_id', store=True, index=True, string='Đơn bán')
    product_id = fields.Many2one(related='sale_line_id.product_id', string='Sản phẩm')
    # Khóa tra lại = đúng chuỗi số hóa đơn lưu trên phiếu xuất kho (misa_invoice_no) — tra lại
    # theo khóa này nên không chuẩn hóa thêm.
    invoice_no = fields.Char(string='Số hóa đơn', required=True, index=True)
    invoice_series = fields.Char(string='Ký hiệu hóa đơn')
    # Danh tính hóa đơn để gộp/lọc/hẹn thu — số hóa đơn có thể trùng giữa 2 ký hiệu (xem
    # invoice_identity). invoice_no ở trên chỉ là khóa để tra lại MISA. Tính từ chính các cột đã
    # lưu để không bao giờ rỗng: bản 18.0.1.0.2 ghi tay field này lúc đọc chứng từ, dòng lưu trước
    # đó để rỗng và bị gộp hết vào 1 hàng (hàng "HĐ 00002954" 2.338 chứng từ trên staging).
    invoice_key = fields.Char(
        string='Mã nhận diện hóa đơn', compute='_compute_invoice_key', store=True, index=True,
    )
    invoice_date = fields.Date(string='Ngày hóa đơn')
    due_date = fields.Date(string='Hạn thu', index=True)
    due_source = fields.Selection([
        ('payment_term', 'Theo điều khoản thanh toán của đơn'),
        ('invoice_date', 'Đơn không có điều khoản — đến hạn ngay ngày hóa đơn'),
    ], string='Cách tính hạn thu')
    voucher_refid = fields.Char(string='MISA refid chứng từ')
    voucher_refno = fields.Char(string='Số chứng từ', index=True)
    # Tổng tiền chứng từ lúc đọc dòng — tra lại mà tổng không đổi thì dùng lại dòng đã lưu,
    # khỏi đọc lại chi tiết (xem reusable_voucher_states).
    voucher_total = fields.Float(string='Tổng tiền chứng từ')
    partner_code = fields.Char(string='Mã KH (MISA)')
    partner_name = fields.Char(string='Tên khách hàng (MISA)')
    saler_code = fields.Char(string='Mã sale MISA', index=True)
    item_code = fields.Char(string='Mã hàng (MISA)')
    description = fields.Char(string='Tên hàng (MISA)')
    quantity = fields.Float(string='Số lượng (MISA)')
    unit_name = fields.Char(string='ĐVT (MISA)')
    amount = fields.Float(string='Tiền có VAT')
    match_scope = fields.Selection([
        ('order', 'Theo mã đơn ghi trên chứng từ'),
        ('invoice', 'Theo hàng trên phiếu của hóa đơn (chứng từ không ghi / ghi sai mã đơn)'),
    ], string='Khớp trong phạm vi')
    match_by = fields.Selection([
        ('code', 'Đúng mã hàng'),
        ('name', 'Đúng tên hàng (mã hàng đã đổi)'),
        ('component', 'Mã sản phẩm con của combo — số lượng là của mã con'),
    ], string='Khớp bằng')
    paid_state = fields.Selection(PAID_STATE_SELECTION, string='Tình trạng thu', index=True)

    @api.depends('invoice_no', 'invoice_series', 'invoice_date')
    def _compute_invoice_key(self):
        for line in self:
            line.invoice_key = invoice_identity(line.invoice_no, line.invoice_series, line.invoice_date)
