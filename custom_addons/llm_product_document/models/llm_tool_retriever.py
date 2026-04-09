import logging

from odoo import models

_logger = logging.getLogger(__name__)


class LLMToolKnowledge(models.Model):
    _inherit = "llm.tool"

    def _process_search_results(self, chunks, top_k, top_n):
        """Override to inject product_name/product_code into chunk results."""
        result_data = super()._process_search_results(chunks, top_k, top_n)

        # Collect unique resource IDs from the results
        resource_ids = list({entry["resource_id"] for entry in result_data})
        resources = self.env["llm.resource"].browse(resource_ids)

        # Build map: resource_id -> {product_name, product_code}
        product_map = {}
        for resource in resources:
            if resource.res_model != "product.document":
                continue
            doc = self.env["product.document"].browse(resource.res_id)
            if not doc.exists():
                continue
            product = doc._get_product_info()
            if product.exists():
                product_map[resource.id] = {
                    "product_name": product.display_name,
                    "product_code": product.default_code or "",
                }

        for entry in result_data:
            info = product_map.get(entry["resource_id"])
            if info:
                entry.update(info)

        return result_data
