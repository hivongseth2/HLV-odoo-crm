import logging

from odoo import models

_logger = logging.getLogger(__name__)


class ProductDocument(models.Model):
    _inherit = "product.document"

    def _get_product_info(self):
        """Get the product template linked to this document."""
        self.ensure_one()
        if self.res_model == "product.template":
            return self.env["product.template"].browse(self.res_id)
        elif self.res_model == "product.product":
            variant = self.env["product.product"].browse(self.res_id)
            if variant.exists():
                return variant.product_tmpl_id
        return self.env["product.template"]

    def _build_product_context_header(self):
        """Build a markdown header with product metadata."""
        self.ensure_one()
        product = self._get_product_info()
        if not product.exists():
            return ""
        lines = [f"# Tài liệu sản phẩm: {product.display_name}"]
        if product.default_code:
            lines.append(f"**Mã sản phẩm:** {product.default_code}")
        if product.barcode:
            lines.append(f"**Barcode:** {product.barcode}")
        if product.categ_id:
            lines.append(f"**Danh mục:** {product.categ_id.complete_name}")
        if product.list_price:
            lines.append(f"**Giá bán:** {product.list_price:,.0f}")
        lines.append("")
        return "\n".join(lines)

    def llm_get_retrieval_details(self):
        """Provide retrieval details – delegates to the wrapped ir.attachment."""
        self.ensure_one()
        attachment = self.ir_attachment_id
        data_type = "url" if attachment.type == "url" else "binary"
        return {
            "type": data_type,
            "field": "datas" if data_type == "binary" else "url",
            "target_fields": {
                "content": "datas",
                "mimetype": "mimetype",
                "filename": "name",
                "type": "type",
            },
        }

    def llm_get_fields(self, _record=None):
        """Return product context header + attachment content.

        The base parse loop now accumulates content across fields, so
        the product metadata header will appear before the document body
        in the final ``resource.content``.
        """
        self.ensure_one()
        attachment = self.ir_attachment_id
        result = []

        # Product context as first field
        header = self._build_product_context_header()
        if header:
            result.append({
                "field_name": "product_context",
                "mimetype": "text/plain",
                "rawcontent": header,
            })

        # Actual document content from attachment
        is_markdown = (
            attachment.name
            and attachment.name.lower().endswith(".md")
            and attachment.mimetype == "application/octet-stream"
        )
        if attachment.raw:
            result.append({
                "field_name": "datas",
                "mimetype": "text/markdown" if is_markdown else attachment.mimetype,
                "rawcontent": attachment.raw,
            })

        return result
