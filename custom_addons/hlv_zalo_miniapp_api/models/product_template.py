# -*- coding: utf-8 -*-
from odoo import models, fields

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    x_zalo_price = fields.Float(
        string='Giá Zalo App',
        digits='Product Price',
        help='Giá hiển thị trên Zalo Mini App',
    )
    x_active_zalo = fields.Boolean(
        string='Hiển thị trên Zalo',
        default=False,
        help='Chỉ sản phẩm có flag này = True mới xuất hiện trên Zalo Mini App',
    )
