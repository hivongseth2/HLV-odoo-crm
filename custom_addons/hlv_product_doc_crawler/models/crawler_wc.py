import logging

import requests
from markdownify import markdownify as md

from odoo import _, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class HlvDocCrawlerWC(models.Model):
    """WooCommerce-specific crawler methods."""

    _inherit = "hlv.doc.crawler"

    # ─── WC API ───────────────────────────────────────────────────────────────

    def _wc_get(self, path):
        """Gọi WooCommerce REST API (query-param auth)."""
        self.ensure_one()
        if not self.wc_key or not self.wc_secret:
            raise UserError(_("Thiếu Consumer Key / Consumer Secret."))
        sep = "&" if "?" in path else "?"
        url = (
            f"{self.wc_domain.rstrip('/')}/wp-json/wc/v3{path}"
            f"{sep}consumer_key={self.wc_key}&consumer_secret={self.wc_secret}"
        )
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        return resp.json()

    # ─── Helpers xây dựng nội dung WC ─────────────────────────────────────────

    def _build_product_markdown(self, wc_product):
        """Xây dựng tài liệu markdown từ dữ liệu WC API."""
        lines = [f"# {wc_product.get('name', '')}"]
        lines.append("")
        lines.append(f"**SKU:** {wc_product.get('sku', '')}")

        if wc_product.get("categories"):
            cats = ", ".join(c["name"] for c in wc_product["categories"])
            lines.append(f"**Danh mục:** {cats}")

        if wc_product.get("permalink"):
            lines.append(f"**Trang sản phẩm:** {wc_product['permalink']}")

        if wc_product.get("short_description"):
            text = self._clean_html(wc_product["short_description"])
            if text:
                lines.append("\n## Mô tả ngắn\n")
                lines.append(text)

        if wc_product.get("description"):
            text = self._clean_html(wc_product["description"])
            if text:
                lines.append("\n## Mô tả chi tiết\n")
                lines.append(text)

        if wc_product.get("attributes"):
            attrs = [
                f"- **{a['name']}:** {', '.join(a.get('options', []))}"
                for a in wc_product["attributes"]
                if a.get("options")
            ]
            if attrs:
                lines.append("\n## Thông số kỹ thuật\n")
                lines.extend(attrs)

        return "\n".join(lines)

    # ─── WC processing ────────────────────────────────────────────────────────

    def _process_wc_product(self, product, sku, line, collection):
        """Xử lý 1 sản phẩm qua WooCommerce API. Trả về True nếu tìm thấy."""
        wc_data = self._wc_get(f"/products?sku={sku}&per_page=5")
        if not wc_data:
            line.write({"status": "not_found"})
            return False

        wc_product = wc_data[0]
        content = self._build_product_markdown(wc_product)
        doc = self._ensure_product_document(product, sku, content)

        resource = None
        if self.auto_index or collection:
            resource = self._ensure_resource(doc, collection)
            if self.auto_index:
                resource.process_resource()

        line.write(
            {
                "status": "found",
                "wc_url": wc_product.get("permalink", ""),
                "document_id": doc.ir_attachment_id.id,
                "resource_id": resource.id if resource else False,
            }
        )
        return True
