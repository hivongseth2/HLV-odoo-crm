import base64
import logging
import re

import requests
from markdownify import markdownify as md

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class HlvDocCrawler(models.Model):
    _name = "hlv.doc.crawler"
    _description = "Crawler Tài liệu Sản phẩm từ Website"
    _rec_name = "name"

    name = fields.Char(required=True, default="Crawler Hoàng Long Vũ")
    source = fields.Selection(
        [("hoanglongvu", "Hoàng Long Vũ"), ("mecsu", "MecSu")],
        required=True,
        default="hoanglongvu",
        string="Nguồn dữ liệu",
    )

    # === Kết nối WooCommerce API ===
    wc_domain = fields.Char(
        string="Domain website",
        default="https://hoanglongvu.com",
        help="VD: https://hoanglongvu.com",
    )
    wc_key = fields.Char(string="Consumer Key")
    wc_secret = fields.Char(string="Consumer Secret")

    # === Cấu hình batch ===
    skip = fields.Integer(
        default=0,
        string="Bỏ qua (skip)",
        help="Số sản phẩm bỏ qua từ đầu danh sách (offset)",
    )
    limit = fields.Integer(
        default=30,
        string="Giới hạn xử lý (limit)",
        help="Số sản phẩm xử lý tối đa mỗi lần chạy (nên ≤ 50 khi bật RAG)",
    )
    use_max_products = fields.Boolean(
        default=False,
        string="Giới hạn tổng số sản phẩm",
        help="Bật để giới hạn tổng số sản phẩm xử lý trong toàn bộ session (dùng để test)",
    )
    max_products = fields.Integer(
        default=100,
        string="Số sản phẩm tối đa",
        help="Dừng sau khi đã xử lý đủ số lượng này (bất kể tìm thấy hay không)",
    )

    # === Tích hợp RAG ===
    auto_index = fields.Boolean(
        default=True,
        string="Tự động lập chỉ mục RAG",
        help="Sau khi tạo tài liệu, tự động chạy toàn bộ pipeline RAG (retrieve → parse → chunk → embed)",
    )
    collection_id = fields.Many2one(
        "llm.knowledge.collection",
        string="Collection RAG",
        help="Để trống để dùng collection 'Tài liệu sản phẩm' mặc định",
    )

    # === Trạng thái ===
    state = fields.Selection(
        [("idle", "Chờ"), ("running", "Đang chạy"), ("done", "Hoàn thành")],
        default="idle",
        string="Trạng thái",
    )
    last_run = fields.Datetime(string="Lần chạy gần nhất", readonly=True)

    # === Log ===
    line_ids = fields.One2many("hlv.doc.crawler.line", "crawler_id", string="Log kết quả")
    found_count = fields.Integer(compute="_compute_counts", string="Tìm thấy", store=True)
    not_found_count = fields.Integer(compute="_compute_counts", string="Không tìm thấy", store=True)
    error_count = fields.Integer(compute="_compute_counts", string="Lỗi", store=True)

    @api.depends("line_ids.status")
    def _compute_counts(self):
        for rec in self:
            lines = rec.line_ids
            rec.found_count = len(lines.filtered(lambda l: l.status == "found"))
            rec.not_found_count = len(lines.filtered(lambda l: l.status == "not_found"))
            rec.error_count = len(lines.filtered(lambda l: l.status == "error"))

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

    # ─── Helpers xây dựng nội dung ────────────────────────────────────────────

    def _clean_html(self, html_content):
        """Xóa script/style và chuyển HTML → markdown."""
        if not html_content:
            return ""
        clean = re.sub(
            r"<(script|style)[^>]*>.*?</\1>", "", html_content, flags=re.DOTALL
        )
        return md(clean, heading_style="ATX", bullets="-", strip=["img"]).strip()

    def _build_product_markdown(self, wc_product):
        """Xây dựng tài liệu markdown từ dữ liệu WC API."""
        lines = [f"# {wc_product.get('name', '')}"]
        lines.append("")
        lines.append(f"**SKU:** {wc_product.get('sku', '')}")

        if wc_product.get("categories"):
            cats = ", ".join(c["name"] for c in wc_product["categories"])
            lines.append(f"**Danh mục:** {cats}")

        price = wc_product.get("regular_price") or wc_product.get("price")
        if price:
            lines.append(f"**Giá niêm yết:** {price}")

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

    # ─── Helpers tạo/cập nhật bản ghi ─────────────────────────────────────────

    def _ensure_product_document(self, product, sku, content):
        """Tạo hoặc cập nhật product.document (file .md) cho sản phẩm."""
        attachment_name = f"{sku}_web.md"
        encoded = base64.b64encode(content.encode("utf-8")).decode()

        existing = self.env["product.document"].search(
            [
                ("res_model", "=", "product.template"),
                ("res_id", "=", product.id),
                ("name", "=", attachment_name),
            ],
            limit=1,
        )
        if existing:
            existing.ir_attachment_id.write(
                {"datas": encoded, "mimetype": "application/octet-stream"}
            )
            return existing

        return self.env["product.document"].create(
            {
                "name": attachment_name,
                "datas": encoded,
                "mimetype": "application/octet-stream",
                "res_model": "product.template",
                "res_id": product.id,
            }
        )

    def _get_rag_collection(self):
        """Trả về collection RAG (ưu tiên cấu hình, sau đó auto-discover)."""
        if self.collection_id:
            return self.collection_id
        ICP = self.env["ir.config_parameter"].sudo()
        col_id = ICP.get_param("llm_product_document.collection_id", "0")
        if col_id and col_id != "0":
            c = self.env["llm.knowledge.collection"].browse(int(col_id))
            if c.exists():
                return c
        return self.env["llm.knowledge.collection"].search(
            [("name", "ilike", "Tài liệu sản phẩm")], limit=1
        )

    def _ensure_resource(self, doc, collection):
        """Tạo hoặc trả về llm.resource cho document này."""
        model_id = self.env["ir.model"]._get_id("product.document")
        existing = self.env["llm.resource"].search(
            [("model_id", "=", model_id), ("res_id", "=", doc.id)], limit=1
        )
        if existing:
            vals = {}
            if collection and collection.id not in existing.collection_ids.ids:
                vals["collection_ids"] = [(4, collection.id)]
            # Reset về draft để nội dung mới được lập chỉ mục lại
            vals["state"] = "draft"
            existing.write(vals)
            return existing

        prefix = ""
        if doc.res_model == "product.template":
            product = self.env["product.template"].browse(doc.res_id)
            if product.exists():
                prefix = f"[{product.default_code or 'N/A'}] "

        return self.env["llm.resource"].create(
            {
                "name": f"{prefix}{doc.name}",
                "model_id": model_id,
                "res_id": doc.id,
                "collection_ids": [(4, collection.id)] if collection else [],
            }
        )

    # ─── Action chính ──────────────────────────────────────────────────────────

    def action_run(self):
        """Chạy crawler cho batch được cấu hình."""
        self.ensure_one()
        self.write({"state": "running", "last_run": fields.Datetime.now()})

        products = self.env["product.template"].search(
            [("default_code", "!=", False), ("default_code", "!=", "")],
            offset=self.skip,
            limit=self.limit,
        )

        collection = self._get_rag_collection()
        Line = self.env["hlv.doc.crawler.line"]
        processed = 0

        for product in products:
            if self.use_max_products and processed >= self.max_products:
                break
            sku = product.default_code
            line = Line.create(
                {
                    "crawler_id": self.id,
                    "product_id": product.id,
                    "sku": sku,
                    "status": "pending",
                    "run_date": fields.Datetime.now(),
                }
            )
            try:
                wc_data = self._wc_get(f"/products?sku={sku}&per_page=5")
                if not wc_data:
                    line.write({"status": "not_found"})
                    continue

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
            except Exception as e:
                _logger.error(
                    "Crawler [%s] SKU=%s: %s", self.name, sku, e, exc_info=True
                )
                line.write({"status": "error", "error_msg": str(e)[:500]})
            finally:
                processed += 1

        self.write({"state": "done"})
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Crawler hoàn thành"),
                "message": _(
                    "Đã xử lý %d sản phẩm  |  Tìm thấy: %d  |  Không tìm thấy: %d  |  Lỗi: %d"
                )
                % (
                    len(products),
                    self.found_count,
                    self.not_found_count,
                    self.error_count,
                ),
                "type": "success",
                "sticky": True,
            },
        }

    def action_clear_logs(self):
        """Xóa toàn bộ log của lần chạy này."""
        self.ensure_one()
        self.line_ids.unlink()
        self.write({"state": "idle"})

    # ─── Stat button actions ───────────────────────────────────────────────────

    def _open_lines(self, extra_domain=None):
        self.ensure_one()
        domain = [("crawler_id", "=", self.id)]
        if extra_domain:
            domain += extra_domain
        return {
            "type": "ir.actions.act_window",
            "name": _("Kết quả - %s") % self.name,
            "res_model": "hlv.doc.crawler.line",
            "view_mode": "list,form",
            "domain": domain,
        }

    def action_view_found(self):
        return self._open_lines([("status", "=", "found")])

    def action_view_not_found(self):
        return self._open_lines([("status", "=", "not_found")])

    def action_view_errors(self):
        return self._open_lines([("status", "=", "error")])
