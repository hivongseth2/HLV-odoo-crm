from odoo import models, fields

class ResPartner(models.Model):
    _inherit = 'res.partner'

    hlv_delivery_location_ids = fields.One2many(
        'res.partner.delivery.location',
        'partner_id',
        string='Tọa độ giao hàng'
    )
