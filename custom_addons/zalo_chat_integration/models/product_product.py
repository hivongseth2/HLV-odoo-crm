from odoo import models, fields, api

class ProductProduct(models.Model):
    _name = 'product.product'
    _inherit = ['product.product', 'zalo.vector.mixin']

    def _get_vector_content(self):
        """Content for embedding: Name + Code + Category + Aliases + Description"""
        self.ensure_one()
        
        # Base info
        parts = [
            f"Tên: {self.name}",
            f"Mã: {self.default_code or ''}",
            f"Danh mục: {self.categ_id.name or ''}",
        ]
        
        # Attributes (Variants)
        if self.product_template_attribute_value_ids:
            attrs = ", ".join([v.name for v in self.product_template_attribute_value_ids])
            parts.append(f"Thuộc tính: {attrs}")
            
        # Aliases from Template
        if self.product_tmpl_id.alias_ids:
            aliases = ", ".join([a.alias for a in self.product_tmpl_id.alias_ids])
            parts.append(f"Tên gọi khác: {aliases}")
            
        # Description
        if self.description_sale:
            parts.append(f"Mô tả: {self.description_sale}")
            
        return "\n".join(parts)

    def write(self, vals):
        res = super().write(vals)
        # Auto-update vector if relevant fields change
        # Checking fields to avoid recursion or unnecessary updates
        tracked_fields = {'name', 'default_code', 'description_sale', 'product_template_attribute_value_ids'}
        if any(f in vals for f in tracked_fields):
            for record in self:
                # Use cron or queue job ideally, but synchronous for now for simplicity
                # Or verify if we want to do it immediately. API calls might be slow.
                # Let's DO IT synchronously for now as requested "làm đi" (do it), optimization later.
                try:
                    record._update_vector()
                except Exception:
                    pass # Don't block write if GPT fails
        return res

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            try:
                record._update_vector()
            except Exception:
                pass
        return records
