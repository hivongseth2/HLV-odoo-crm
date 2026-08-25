from odoo import models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def action_open_stock_trace(self):
        self.ensure_one()
        product = self.product_variant_ids[:1]
        return {
            "type": "ir.actions.client",
            "tag": "hlv_stock_trace.dashboard",
            "name": "Theo dõi tồn kho theo thời gian",
            "target": "current",
            "context": {
                "product_id": product.id if product else False,
                "product_name": self.display_name,
            },
        }
