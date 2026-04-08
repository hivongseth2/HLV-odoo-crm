import logging

from odoo import _, fields, models

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = "product.template"

    llm_resource_ids = fields.One2many(
        "llm.resource",
        "product_tmpl_id",
        string="Tài nguyên AI",
    )
    llm_resource_count = fields.Integer(
        string="Tài nguyên AI",
        compute="_compute_llm_resource_count",
    )

    def _compute_llm_resource_count(self):
        for product in self:
            product.llm_resource_count = len(product.llm_resource_ids)

    def _get_product_doc_collection(self):
        """Get the product document collection.

        Lookup order:
        1. System parameter ``llm_product_document.collection_id``
        2. Search by name "Tài liệu sản phẩm"

        When found via name search, the system parameter is updated so
        subsequent calls are faster.
        """
        ICP = self.env["ir.config_parameter"].sudo()
        col_id = ICP.get_param("llm_product_document.collection_id", "0")
        collection = self.env["llm.knowledge.collection"]
        if col_id and col_id != "0":
            collection = self.env["llm.knowledge.collection"].browse(int(col_id))
            if collection.exists():
                return collection

        # Fallback: search by name
        collection = self.env["llm.knowledge.collection"].search(
            [("name", "ilike", "Tài liệu sản phẩm")], limit=1
        )
        if collection:
            ICP.set_param("llm_product_document.collection_id", str(collection.id))
        return collection

    def action_sync_product_documents(self):
        """Sync all product documents of selected products into the knowledge collection."""
        collection = self._get_product_doc_collection()
        if not collection:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Lỗi"),
                    "message": _(
                        "Chưa tìm thấy collection 'Tài liệu sản phẩm'. "
                        "Hãy tạo collection với tên 'Tài liệu sản phẩm' trong module Kiến thức trước."
                    ),
                    "type": "danger",
                },
            }

        ProductDoc = self.env["product.document"]
        Resource = self.env["llm.resource"]
        model_id = self.env["ir.model"]._get_id("product.document")

        created = 0
        linked = 0

        for product in self:
            # Get all documents of this product template + variants
            docs = ProductDoc.search([
                "|",
                "&", ("res_model", "=", "product.template"), ("res_id", "=", product.id),
                "&", ("res_model", "=", "product.product"), ("res_id", "in", product.product_variant_ids.ids),
            ])

            for doc in docs:
                # Check if resource already exists
                existing = Resource.search([
                    ("model_id", "=", model_id),
                    ("res_id", "=", doc.id),
                ], limit=1)

                if existing:
                    # Link to collection if not already there
                    if collection.id not in existing.collection_ids.ids:
                        existing.write({"collection_ids": [(4, collection.id)]})
                        linked += 1
                else:
                    # Build a descriptive name
                    name = f"[{product.default_code or 'N/A'}] {doc.name or doc.ir_attachment_id.name}"
                    Resource.create({
                        "name": name,
                        "model_id": model_id,
                        "res_id": doc.id,
                        "collection_ids": [(4, collection.id)],
                    })
                    created += 1

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Đồng bộ tài liệu sản phẩm"),
                "message": _("Đã tạo %d tài nguyên mới, liên kết %d tài nguyên có sẵn.") % (created, linked),
                "type": "success",
            },
        }

    def action_view_llm_resources(self):
        """Open resources linked to this product."""
        self.ensure_one()
        return {
            "name": _("Tài nguyên AI - %s") % self.display_name,
            "type": "ir.actions.act_window",
            "res_model": "llm.resource",
            "view_mode": "list,form",
            "domain": [("product_tmpl_id", "=", self.id)],
        }
