from odoo import fields, models


class MisaInvoiceGroupedMatch(models.Model):
    _name = 'misa.invoice.grouped.match'
    _description = 'Lượt khớp 1 dòng hàng xuất HĐ chung (misa.invoice.grouped.line) với 1 phiếu xuất kho'
    _order = 'matched_at'

    # Cùng vai trò với misa.invoice.customs.match, cho 1 dòng hàng xuất HĐ chung bị chia xuất
    # kho thành nhiều đợt (nhiều phiếu của cùng 1 đơn bán).
    line_id = fields.Many2one(
        'misa.invoice.grouped.line', string='Dòng hàng xuất HĐ chung', required=True, ondelete='cascade', index=True,
    )
    picking_id = fields.Many2one('stock.picking', string='Phiếu xuất kho', required=True, ondelete='cascade', index=True)
    quantity = fields.Float(string='Số lượng khớp từ phiếu này', required=True)
    # Tiền (có VAT) quy cho phiếu này — cộng dồn vào stock_picking.misa_invoice_grouped_matched_amount.
    amount = fields.Float(string='Thành tiền quy cho phiếu này (có VAT)')
    is_manual = fields.Boolean(default=False)
    matched_by_id = fields.Many2one('res.users', string='Người khớp')
    matched_at = fields.Datetime(string='Thời điểm khớp')
