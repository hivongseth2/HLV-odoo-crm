from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    x_packer_name = fields.Char(
        string='Tên người đóng',
        help='Tên hiển thị khi assign và đánh giá KPI đóng gói.',
    )

    x_sale_plan_mention_names = fields.Char(
        string='Sale Plan mention aliases',
        help='Danh sach alias nhan thong bao tren trang /sale_plan, phan tach bang dau phay. Vi du: thanhnhan, thanhluan.',
    )
