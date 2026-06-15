from odoo import models, fields

class ResPartnerDeliveryLocation(models.Model):
    _name = 'res.partner.delivery.location'
    _description = 'Delivery Geocode Cache'

    partner_id = fields.Many2one('res.partner', string='Liên hệ', required=True, ondelete='cascade', index=True)
    address = fields.Char(string='Địa chỉ giao hàng', required=True, index=True)
    latitude = fields.Float(string='Vĩ độ (Latitude)', digits=(10, 7))
    longitude = fields.Float(string='Kinh độ (Longitude)', digits=(10, 7))

    _sql_constraints = [
        ('partner_address_uniq', 'unique (partner_id, address)', 'Địa chỉ này đã tồn tại tọa độ cho khách hàng này!')
    ]
