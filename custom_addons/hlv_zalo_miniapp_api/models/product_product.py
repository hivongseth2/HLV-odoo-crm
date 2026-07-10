# -*- coding: utf-8 -*-
from odoo import models, fields


class ProductProduct(models.Model):
    _inherit = 'product.product'

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

    def action_sync_to_wordpress(self):
        """
        Dummy method để bypass lỗi ParseError khi Odoo compile view product.product_normal_form_view.
        Nút bấm này được kế thừa từ wordpress_sync vào product.template nhưng product.product cũng kế thừa view.
        """
        for record in self:
            if hasattr(record.product_tmpl_id, 'action_sync_to_wordpress'):
                return record.product_tmpl_id.action_sync_to_wordpress()
        return True