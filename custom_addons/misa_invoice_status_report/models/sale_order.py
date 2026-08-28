from odoo import fields, models


class SaleOrderMisaInvoiceStatus(models.Model):
    _inherit = 'sale.order'

    # Chiều ngược của stock.picking.misa_invoice_sale_order_ids — dùng cùng bảng quan hệ
    # để tra "đơn hàng này gắn với những phiếu xuất kho nào" cho tab Đơn hàng trên dashboard.
    misa_invoice_picking_ids = fields.Many2many(
        'stock.picking', 'misa_invoice_picking_sale_order_rel', 'order_id', 'picking_id',
        string='Phiếu xuất kho liên quan',
    )

    # Đánh dấu "đã nhắc sale xuất hóa đơn" — dùng để HIGHLIGHT đơn này trên tab Đơn hàng (cả
    # dashboard nội bộ lẫn /misa_sale_status) cho tới khi đơn được xuất HĐ đủ (xem
    # _misa_invoice_order_row: chỉ highlight khi state != 'invoiced', KHÔNG tự xóa field này để
    # còn giữ lịch sử "đã từng nhắc lúc nào, ai nhắc" — xem action_send_misa_invoice_reminder.
    misa_invoice_reminder_at = fields.Datetime(string='Lần nhắc xuất HĐ gần nhất', copy=False)
    misa_invoice_reminder_by_id = fields.Many2one('res.users', string='Người nhắc xuất HĐ', copy=False)
