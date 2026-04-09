import logging

from odoo import _, models

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

    def _get_collection(self):
        """Find the RAG collection for product documents."""
        ICP = self.env["ir.config_parameter"].sudo()
        col_id = ICP.get_param("llm_product_document.collection_id", "0")
        if col_id and col_id != "0":
            c = self.env["llm.knowledge.collection"].browse(int(col_id))
            if c.exists():
                return c
        collection = self.env["llm.knowledge.collection"].search(
            [("name", "ilike", "Tài liệu sản phẩm")], limit=1
        )
        if collection:
            ICP.set_param("llm_product_document.collection_id", str(collection.id))
        return collection

    def action_sync_and_index(self):
        """Sync selected documents to RAG and immediately run full indexing pipeline."""
        collection = self._get_collection()
        if not collection:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Lỗi"),
                    "message": _(
                        "Chưa tìm thấy collection 'Tài liệu sản phẩm'. "
                        "Hãy tạo collection với tên này trong module Kiến thức trước."
                    ),
                    "type": "danger",
                },
            }

        Resource = self.env["llm.resource"]
        model_id = self.env["ir.model"]._get_id("product.document")
        resources_to_process = Resource

        for doc in self:
            existing = Resource.search(
                [("model_id", "=", model_id), ("res_id", "=", doc.id)], limit=1
            )
            if existing:
                if collection.id not in existing.collection_ids.ids:
                    existing.write({"collection_ids": [(4, collection.id)]})
                # Reset to draft so updated content gets re-indexed
                existing.write({"state": "draft"})
                resources_to_process |= existing
            else:
                # Build name: [SKU] filename
                prefix = ""
                if doc.res_model == "product.template":
                    product = self.env["product.template"].browse(doc.res_id)
                    if product.exists():
                        prefix = f"[{product.default_code or 'N/A'}] "
                elif doc.res_model == "product.product":
                    variant = self.env["product.product"].browse(doc.res_id)
                    if variant.exists():
                        code = variant.default_code or variant.product_tmpl_id.default_code or "N/A"
                        prefix = f"[{code}] "
                name = f"{prefix}{doc.name or doc.ir_attachment_id.name}"
                resources_to_process |= Resource.create({
                    "name": name,
                    "model_id": model_id,
                    "res_id": doc.id,
                    "collection_ids": [(4, collection.id)],
                })

        if resources_to_process:
            resources_to_process.process_resource()

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Lập chỉ mục hoàn tất"),
                "message": _("Đã xử lý %d tài liệu vào AI Knowledge.") % len(resources_to_process),
                "type": "success",
            },
        }
