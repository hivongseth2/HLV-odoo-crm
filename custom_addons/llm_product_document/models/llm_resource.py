import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class LLMResource(models.Model):
    _inherit = "llm.resource"

    product_tmpl_id = fields.Many2one(
        "product.template",
        string="Sản phẩm",
        compute="_compute_product_tmpl_id",
        store=True,
        index=True,
    )

    @api.depends("res_model", "res_id")
    def _compute_product_tmpl_id(self):
        for resource in self:
            product = self.env["product.template"]
            if resource.res_model == "product.document":
                doc = self.env["product.document"].browse(resource.res_id)
                if doc.exists():
                    if doc.res_model == "product.template":
                        product = self.env["product.template"].browse(doc.res_id)
                    elif doc.res_model == "product.product":
                        variant = self.env["product.product"].browse(doc.res_id)
                        if variant.exists():
                            product = variant.product_tmpl_id
            resource.product_tmpl_id = product if product.exists() else False

    def parse(self):
        """Override to prepend product context after normal parsing."""
        result = super().parse()

        # For product.document resources that were just parsed, prepend
        # the product metadata header so embeddings include product info.
        for resource in self.filtered(
            lambda r: r.res_model == "product.document"
            and r.state == "parsed"
            and r.content
        ):
            try:
                doc = self.env["product.document"].browse(resource.res_id)
                if doc.exists():
                    header = doc._build_product_context_header()
                    if header:
                        resource.write({"content": header + "\n" + resource.content})
            except Exception as e:
                _logger.warning(
                    "Could not prepend product context for resource %s: %s",
                    resource.id,
                    e,
                )

        return result
