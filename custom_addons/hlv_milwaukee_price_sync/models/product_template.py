# -*- coding: utf-8 -*-
from odoo import models, fields

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # Define Studio fields explicitly to avoid view errors during module load
    x_studio_gi_web = fields.Monetary(string="Giá Web")
    x_studio_ga_hng_nim_yt = fields.Monetary(string="Giá Niêm Yết")

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

    def action_sync_to_milwaukee_single(self):
        """Trigger sync for this specific product from the list view"""
        self.ensure_one()
        config = self.env['milwaukee.config'].search([('active', '=', True)], limit=1)
        if not config:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Lỗi',
                    'message': 'Chưa cấu hình Milwaukee. Vui lòng thiết lập trong Inventory > Configuration.',
                    'type': 'danger',
                }
            }
        
        return config.with_context(active_ids=self.ids).action_push_prices()
