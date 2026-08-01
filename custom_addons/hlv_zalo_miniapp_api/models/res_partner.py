# -*- coding: utf-8 -*-
from odoo import models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    x_is_default_delivery = fields.Boolean(
        string='Địa chỉ giao hàng mặc định',
        default=False,
        help='Đánh dấu địa chỉ giao hàng mặc định của khách hàng Zalo',
    )
    x_is_zalo_account = fields.Boolean(
        string='Tài khoản Zalo',
        default=False,
        help='Đánh dấu contact đã đăng ký tài khoản Zalo Mini App',
    )