from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    x_delivery_point_id = fields.Many2one(
        'hlv.delivery.point', string='Điểm giao', index=True, ondelete='set null',
        help='Nhiều mã khách Odoo trỏ về cùng một điểm giao vật lý. Điều phối đếm điểm '
             'theo field này, không đếm theo mã khách.',
    )
