import base64
import logging
import re
import urllib.parse

import requests
from markdownify import markdownify as md

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

MECSU_BASE = "https://mecsu.vn"


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

    # === Cấu hình MecSu ===
    mecsu_similarity_threshold = fields.Float(
        default=0.65,
        string="Ngưỡng tương đồng",
        help="Điểm tương đồng tối thiểu (0.0–1.0) để chấp nhận kết quả. "
             "1.0 = SKU khớp chính xác. Mặc định 0.65 (khớp tên tương đối).",
    )

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

    # ─── MecSu crawler ────────────────────────────────────────────────────────

    def _mecsu_headers(self):
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    def _mecsu_get(self, url):
        """Lấy HTML từ một URL của mecsu.vn."""
        resp = requests.get(url, headers=self._mecsu_headers(), timeout=25)
        resp.raise_for_status()
        return resp.text

    def _mecsu_parse_listing(self, html):
        """Phân tích trang danh sách sản phẩm MecSu, trả về list {name, sku, url}.

        Hoạt động cả khi server render SSR lẫn khi trả về HTML tĩnh (không JS).
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            _logger.warning("Thư viện bs4 chưa cài — không phân tích được HTML MecSu.")
            return []

        soup = BeautifulSoup(html, "html.parser")
        seen_urls = set()
        results = []

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if "/chi-tiet/" not in href:
                continue
            full_url = (
                href if href.startswith("http") else f"{MECSU_BASE}{href}"
            )
            if full_url in seen_urls:
                continue

            name = a_tag.get_text(strip=True)
            if not name or len(name) < 5:
                continue

            # Tìm mã sản phẩm gần thẻ liên kết này
            sku = ""
            # Search within parent element text
            container = a_tag.parent
            if container:
                parent_text = container.get_text(" ", strip=True)
                m = re.search(
                    r"(?:Mã\s+sản\s+phẩm|MPN)[:\s]+([A-Z0-9][A-Z0-9\-]+)", parent_text
                )
                if m:
                    sku = m.group(1)

            seen_urls.add(full_url)
            results.append({"name": name, "sku": sku, "url": full_url})

        return results

    def _mecsu_score(self, odoo_code, odoo_name, candidate):
        """Tính điểm tương đồng giữa sản phẩm Odoo và kết quả MecSu (0.0–1.0).

        Ưu tiên khớp SKU chính xác trước, sau đó so tên bằng SequenceMatcher.
        """
        from difflib import SequenceMatcher

        cand_sku = (candidate.get("sku") or "").upper().strip()
        odoo_code_norm = (odoo_code or "").upper().strip()

        # Khớp SKU: MecSu sku thường có dạng BRAND-ORIGINAL_CODE
        if odoo_code_norm and cand_sku:
            if cand_sku == odoo_code_norm:
                return 1.0
            if cand_sku.endswith("-" + odoo_code_norm):
                return 1.0
            if odoo_code_norm in cand_sku:
                return 0.92

        # Khớp tên sản phẩm
        odoo_norm = (odoo_name or "").lower().strip()
        cand_norm = (candidate.get("name") or "").lower().strip()
        if not odoo_norm or not cand_norm:
            return 0.0

        ratio = SequenceMatcher(None, odoo_norm, cand_norm).ratio()

        # Bonus: nếu Odoo code xuất hiện trong tên MecSu
        if odoo_code_norm and odoo_code_norm.lower() in cand_norm:
            ratio = min(1.0, ratio + 0.2)

        return ratio

    def _mecsu_search(self, odoo_code, odoo_name, max_pages=2):
        """Tìm kiếm sản phẩm trên mecsu.vn.

        Thử search theo SKU trước, sau đó theo tên nếu chưa đủ kết quả.
        Trả về list ứng viên {name, sku, url}.
        """
        candidates = []
        seen_urls = set()

        def _add_unique(items):
            for item in items:
                if item["url"] not in seen_urls:
                    seen_urls.add(item["url"])
                    candidates.append(item)

        # Chiến lược 1: tìm theo mã SKU
        if odoo_code:
            for page in range(1, max_pages + 1):
                try:
                    url = (
                        f"{MECSU_BASE}/site"
                        f"?q={urllib.parse.quote(odoo_code)}&view=table"
                        + (f"&page={page}" if page > 1 else "")
                    )
                    html = self._mecsu_get(url)
                    page_items = self._mecsu_parse_listing(html)
                    _add_unique(page_items)
                    if not page_items:
                        break
                except Exception as e:
                    _logger.warning("MecSu search(code=%s, page=%d): %s", odoo_code, page, e)
                    break

        # Chiến lược 2: tìm theo 3-4 từ đầu tên nếu chưa có đủ ứng viên
        if odoo_name and len(candidates) < 5:
            short_name = " ".join(odoo_name.split()[:4])
            for page in range(1, max_pages + 1):
                try:
                    url = (
                        f"{MECSU_BASE}/site"
                        f"?q={urllib.parse.quote(short_name)}&view=table"
                        + (f"&page={page}" if page > 1 else "")
                    )
                    html = self._mecsu_get(url)
                    page_items = self._mecsu_parse_listing(html)
                    _add_unique(page_items)
                    if not page_items:
                        break
                except Exception as e:
                    _logger.warning("MecSu search(name=%s, page=%d): %s", short_name, page, e)
                    break

        return candidates

    def _mecsu_fetch_detail(self, url):
        """Lấy trang chi tiết sản phẩm MecSu và dựng nội dung markdown."""
        try:
            html = self._mecsu_get(url)
        except Exception as e:
            _logger.warning("MecSu fetch detail failed: %s — %s", url, e)
            return ""

        try:
            from bs4 import BeautifulSoup
        except ImportError:
            # Fallback: dùng regex đơn giản
            return self._clean_html(html)

        soup = BeautifulSoup(html, "html.parser")

        # Xóa phần không cần thiết
        for tag in soup.find_all(["script", "style", "nav", "footer"]):
            tag.decompose()

        lines = []

        # Tiêu đề sản phẩm
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else ""
        if title:
            lines.append(f"# {title}")
            lines.append("")

        # MPN / mã sản phẩm MecSu
        mpn_m = re.search(r"MPN[:\s]+([A-Z0-9][A-Z0-9\-]+)", html)
        if mpn_m:
            lines.append(f"**Mã sản phẩm (MecSu MPN):** {mpn_m.group(1)}")

        # Giá bán
        price_m = re.search(r"([\d.,]+\s*đ\s*/\s*\w+)", html)
        if price_m:
            lines.append(f"**Giá:** {price_m.group(1)}")

        lines.append(f"**Nguồn:** {url}")
        lines.append("")

        # Bảng thông số kỹ thuật (lấy bảng đầu tiên có ít nhất 3 hàng)
        for tbl in soup.find_all("table"):
            rows = []
            for tr in tbl.find_all("tr"):
                cells = [
                    td.get_text(strip=True)
                    for td in tr.find_all(["td", "th"])
                ]
                if len(cells) >= 2 and cells[0] and cells[1]:
                    rows.append(f"- **{cells[0]}:** {cells[1]}")
            if len(rows) >= 3:
                lines.append("## Thông số kỹ thuật")
                lines.extend(rows)
                lines.append("")
                break

        # PDF datasheet nếu có
        pdf_link = soup.find("a", href=re.compile(r"\.pdf$", re.I))
        if pdf_link:
            pdf_href = pdf_link["href"]
            if not pdf_href.startswith("http"):
                pdf_href = f"{MECSU_BASE}{pdf_href}"
            lines.append(f"**Tài liệu kỹ thuật (PDF):** {pdf_href}")
            lines.append("")

        return "\n".join(lines) if lines else ""

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
                if self.source == "hoanglongvu":
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

                elif self.source == "mecsu":
                    candidates = self._mecsu_search(sku, product.name)

                    # Tính điểm và chọn ứng viên tốt nhất
                    best = None
                    best_score = 0.0
                    for candidate in candidates:
                        score = self._mecsu_score(sku, product.name, candidate)
                        if score > best_score:
                            best_score = score
                            best = candidate

                    threshold = self.mecsu_similarity_threshold or 0.65
                    if not best or best_score < threshold:
                        line.write({"status": "not_found"})
                        continue

                    content = self._mecsu_fetch_detail(best["url"])
                    if not content:
                        line.write(
                            {
                                "status": "error",
                                "error_msg": "Không lấy được nội dung trang chi tiết MecSu",
                                "wc_url": best["url"],
                                "match_score": best_score,
                            }
                        )
                        continue

                    doc = self._ensure_product_document(
                        product, f"{sku}_mecsu", content
                    )

                    resource = None
                    if self.auto_index or collection:
                        resource = self._ensure_resource(doc, collection)
                        if self.auto_index:
                            resource.process_resource()

                    line.write(
                        {
                            "status": "found",
                            "wc_url": best["url"],
                            "match_score": best_score,
                            "document_id": doc.ir_attachment_id.id,
                            "resource_id": resource.id if resource else False,
                        }
                    )

                else:
                    line.write(
                        {"status": "error", "error_msg": "Nguồn dữ liệu không được hỗ trợ"}
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
