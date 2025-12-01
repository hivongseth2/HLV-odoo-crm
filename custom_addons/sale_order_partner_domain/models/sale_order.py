# custom_sale_shipping/models/sale_order.py
from odoo import api, fields, models

class SaleOrder(models.Model):
    _inherit = 'sale.order'
    
    partner_shipping_id = fields.Many2one(
        'res.partner',
        string='Địa chỉ giao hàng',
        domain="[('type', 'in', ['contact', 'delivery']), '|', ('parent_id', '=', partner_id), ('id', '=', partner_id)]",
        context={'show_shipping_name_only': True},
        readonly=False,
        store=True,
    )
    
    shipping_display_name = fields.Char(
        string='Tên người nhận',
        compute='_compute_shipping_display_name',
        store=False
    )
    
    @api.depends('partner_shipping_id')
    def _compute_shipping_display_name(self):
        for record in self:
            if record.partner_shipping_id:
                # Chỉ lấy tên contact, không lấy tên công ty cha
                record.shipping_display_name = record.partner_shipping_id.name
            else:
                record.shipping_display_name = ''