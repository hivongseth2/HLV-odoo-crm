from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    x_pickup_point_id = fields.Many2one(
        'hlv.pickup.point', string='Điểm nhận hàng', index=True,
        help='Địa chỉ vật lý để tới lấy hàng. Nhiều mã nhà cung cấp có thể trỏ về cùng một '
             'điểm — định mức thời gian đo theo điểm chứ không theo mã.',
    )
