# -*- coding: utf-8 -*-
from odoo import models, fields

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    milwaukee_id = fields.Char(
        string='Milwaukee Product ID',
        help='ID of this product on the Milwaukee pricing website',
        copy=False,
        index=True
    )
    
    milwaukee_sale_price = fields.Float(
        string='Giá giảm Milwaukee',
        help='Giá sale sẽ được đồng bộ lên website Milwaukee. Nếu để trống hoặc 0, salePrice sẽ là regularPrice.'
    )
