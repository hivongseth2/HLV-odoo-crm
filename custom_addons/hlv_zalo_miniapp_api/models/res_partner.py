# -*- coding: utf-8 -*-
from odoo import models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    x_is_zalo_account = fields.Boolean(
        string='Tài khoản Zalo',
        default=False,
        help='Đánh dấu contact đã đăng ký tài khoản Zalo Mini App',
    )