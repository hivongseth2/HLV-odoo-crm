# -*- coding: utf-8 -*-
from odoo import models, fields


class ResUsers(models.Model):
    _inherit = 'res.users'

    x_packer_name = fields.Char(
        string='Tên hiển thị (Packer)',
        copy=False,
        help='Tên rút gọn hiển thị trong bảng Tiến Độ Đóng Hàng. Nếu để trống sẽ dùng tên tài khoản.',
    )
