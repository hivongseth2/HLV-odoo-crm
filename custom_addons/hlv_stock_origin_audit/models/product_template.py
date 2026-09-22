from odoo import models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def action_open_origin_audit(self):
        self.ensure_one()
        product = self.product_variant_ids[:1]
        return {
            "type": "ir.actions.client",
            "tag": "hlv_stock_origin_audit.dashboard",
            "name": "Điều tra nguồn gốc tồn kho",
            "target": "current",
            "context": {
                "product_id": product.id if product else False,
                "product_name": self.display_name,
            },
        }
