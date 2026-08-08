from odoo import fields, models


class SaleOrderMisaInvoiceStatus(models.Model):
    _inherit = 'sale.order'

    # Chiều ngược của stock.picking.misa_invoice_sale_order_ids — dùng cùng bảng quan hệ
    # để tra "đơn hàng này gắn với những phiếu xuất kho nào" cho tab Đơn hàng trên dashboard.
    misa_invoice_picking_ids = fields.Many2many(
        'stock.picking', 'misa_invoice_picking_sale_order_rel', 'order_id', 'picking_id',
        string='Phiếu xuất kho liên quan',
    )
