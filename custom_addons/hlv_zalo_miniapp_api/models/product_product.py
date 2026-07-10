# -*- coding: utf-8 -*-
from odoo import models, fields


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def action_sync_to_wordpress(self):
        """
        Dummy method để bypass lỗi ParseError khi Odoo compile view product.product_normal_form_view.
        Nút bấm này được kế thừa từ wordpress_sync vào product.template nhưng product.product cũng kế thừa view.
        """
        for record in self:
            if hasattr(record.product_tmpl_id, 'action_sync_to_wordpress'):
                return record.product_tmpl_id.action_sync_to_wordpress()
        return True

    def action_sync_stock_to_wordpress(self):
        """
        Dummy method để bypass lỗi ParseError (tương tự như hàm trên).
        """
        for record in self:
            if hasattr(record.product_tmpl_id, 'action_sync_stock_to_wordpress'):
                return record.product_tmpl_id.action_sync_stock_to_wordpress()
        return True

    def action_open_combo_to_bom_wizard(self):
        """
        Dummy method để bypass lỗi ParseError từ module hlv_combo_to_bom.
        """
        for record in self:
            if hasattr(record.product_tmpl_id, 'action_open_combo_to_bom_wizard'):
                return record.product_tmpl_id.action_open_combo_to_bom_wizard()
        return True