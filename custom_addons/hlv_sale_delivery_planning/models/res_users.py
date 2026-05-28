from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    x_packer_name = fields.Char(
        string='Tên người đóng',
        help='Tên hiển thị khi assign và đánh giá KPI đóng gói.',
    )
