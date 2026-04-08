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

    # === Bộ lọc từ khóa ===
    search_keywords = fields.Text(
        string="Từ khóa tìm kiếm",
        help="Chỉ crawl sản phẩm có tên hoặc mã chứa ít nhất một trong các từ khóa này.\n"
             "Mỗi từ khóa một dòng (hoặc phân cách bằng dấu phẩy). Để trống = crawl tất cả.",
    )
    exclude_keywords = fields.Text(
        string="Từ khóa loại bỏ",
        help="Bỏ qua sản phẩm có tên hoặc mã chứa bất kỳ từ khóa nào ở đây.\n"
             "Mỗi từ khóa một dòng (hoặc phân cách bằng dấu phẩy).",
    )

    # === Cấu hình batch ===
    skip = fields.Integer(
        default=0,
        string="Bỏ qua (skip)",
        help="Số sản phẩm bỏ qua từ đầu danh sách (offset). Tự động tăng khi dùng Next trang.",
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
    auto_next_page = fields.Boolean(
        default=False,
        string="Tự động chuyển trang",
        help="Tự động chạy hết tất cả sản phẩm theo từng trang (skip tăng dần theo limit) "
             "cho đến khi không còn sản phẩm nào hoặc đạt giới hạn tối đa.",
    )
    page_delay = fields.Integer(
        default=3,
        string="Nghỉ giữa trang (giây)",
        help="Số giây chờ giữa mỗi trang khi bật Tự động chuyển trang. Tối thiểu 1 giây.",
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

    # ─── Filter helpers ───────────────────────────────────────────────────────

    def _parse_keywords(self, text):
        """Tách text dạng CSV / newline thành list từ khóa đã lowercase."""
        if not text:
            return []
        items = re.split(r"[,\n]+", text)
        return [k.strip().lower() for k in items if k.strip()]

    def _product_matches_filters(self, product):
        """Fallback Python filter (dự phòng cho ORM domain)."""
        combined = f"{(product.name or '')} {(product.default_code or '')}".lower()

        include = self._parse_keywords(self.search_keywords)
        if include and not any(kw in combined for kw in include):
            return False

        exclude = self._parse_keywords(self.exclude_keywords)
        if exclude and any(kw in combined for kw in exclude):
            return False

        return True

    def _build_search_domain(self):
        """Tạo ORM domain bao gồm cả keyword filters.

        Filter trước khi phân trang để offset/limit hoạt động chính xác
        — tránh tình trạng một trang 0 sản phẩm sau khi lọc.
        """
        domain = [("default_code", "!=", False), ("default_code", "!=", "")]

        # Include: khớp ít nhất 1 từ khóa tìm kiếm (trong tên HOẶC mã SP)
        include = self._parse_keywords(self.search_keywords)
        if include:
            parts = [
                ["|", ("name", "ilike", kw), ("default_code", "ilike", kw)]
                for kw in include
            ]
            combined_inc = parts[0]
            for part in parts[1:]:
                combined_inc = ["|"] + combined_inc + part
            domain += combined_inc

        # Exclude: loại sản phẩm khớp bất kỳ từ khóa từ chối
        exclude = self._parse_keywords(self.exclude_keywords)
        for kw in exclude:
            # NOT (name ilike kw OR code ilike kw)  =  (name NOT ilike kw AND code NOT ilike kw)
            domain += [("name", "not ilike", kw), ("default_code", "not ilike", kw)]

        return domain

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

        Tên sản phẩm được lấy từ URL slug (/chi-tiet/{ten-slug}.{id}) vì link text
        thường chỉ là mã số ngắn (0043188) không dùng được để tính điểm.
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            _logger.warning("Thư viện bs4 chưa cài — không phân tích được HTML MecSu.")
            return []

        soup = BeautifulSoup(html, "html.parser")
        seen_urls = set()
        results = []

        all_chi_tiet = [a["href"] for a in soup.find_all("a", href=True) if "/chi-tiet/" in a["href"]]
        _logger.info("MecSu parse_listing: HTML=%d bytes, chi-tiet raw links=%d", len(html), len(all_chi_tiet))

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if "/chi-tiet/" not in href:
                continue
            full_url = (
                href if href.startswith("http") else f"{MECSU_BASE}{href}"
            )
            if full_url in seen_urls:
                continue

            # Lấy tên từ slug URL: /chi-tiet/bulong-thep-den-8-8-din933-m10x100.0054038
            # → "bulong thep den 8.8 din933 m10x100"
            slug_part = href.split("/chi-tiet/")[-1]
            # Bỏ .{numeric-id} ở cuối
            slug_clean = re.sub(r'\.[0-9]+$', '', slug_part)
            # Chuyển hyphen thành space, chuẩn hóa số với dấu chấm
            # "bulong-thep-den-8-8-din933-m10x100" → "bulong thep den 8.8 din933 m10x100"
            name_from_slug = slug_clean.replace("-", " ")
            # Hợp nhất các cụm số kiểu "8 8" → "8.8", "10 9" → "10.9" (do dấu chấm bị đổi thành hyphen)
            name_from_slug = re.sub(r'\b(\d+) (\d)\b', r'\1.\2', name_from_slug)

            # Dùng tên từ slug nếu đủ dài, không thì thử link text
            link_text = a_tag.get_text(strip=True)
            if len(name_from_slug) >= 8:
                name = name_from_slug
            elif link_text and len(link_text) >= 8:
                name = link_text
            else:
                continue

            seen_urls.add(full_url)
            results.append({"name": name, "sku": "", "url": full_url})

        return results

    def _mecsu_score(self, odoo_code, odoo_name, candidate):
        """Tính điểm tương đồng giữa sản phẩm Odoo và kết quả MecSu (0.0–1.0).

        Dùng token-overlap trên thông số kỹ thuật (kích thước, cấp độ bền, vật liệu)
        thay vì so sánh toàn chuỗi — vì tên tiếng Việt giữa Odoo và MecSu thường khác nhau.
        """
        cand_name = (candidate.get("name") or "").lower()
        odoo_norm = (odoo_name or "").lower()

        # ─── Trích xuất token kỹ thuật từ tên Odoo ───────────────────────────
        # (weight, pattern, normalize_fn)
        token_rules = [
            # Kích thước kiểu M16x50, M8x1.25, Ø25, Ф32
            (1.0, re.compile(r'm\d+(?:[x×]\d+(?:\.\d+)?)?(?:\s*(?:ren\s*lửng|rl))?', re.IGNORECASE)),
            # Độ bền / cấp độ: 8.8, 10.9, 12.9, 4.8, A2, A4
            (0.6, re.compile(r'\b(?:4\.8|5\.6|8\.8|10\.9|12\.9|a2-70|a4-80|a2|a4)\b', re.IGNORECASE)),
            # Tiêu chuẩn DIN/ISO
            (0.4, re.compile(r'(?:din|iso)\s*\d+', re.IGNORECASE)),
            # Chiều dài độc lập (ví dụ: 50mm, 100mm)
            (0.3, re.compile(r'\b\d{2,4}\s*mm\b', re.IGNORECASE)),
        ]

        tokens = []  # list of (weight, norm_text)
        for weight, pattern in token_rules:
            for m in pattern.finditer(odoo_norm):
                t = m.group(0).lower().replace(" ", "").replace("×", "x")
                tokens.append((weight, t))

        # Vật liệu (dùng nhóm riêng vì tên khác nhau nhiều)
        material_odoo = None
        if any(k in odoo_norm for k in ("ss304", "304", "inox", "inox304")):
            material_odoo = "304"
        elif any(k in odoo_norm for k in ("316", "inox316", "ss316")):
            material_odoo = "316"
        elif any(k in odoo_norm for k in ("thép đen", "đen", "carbon", "black", "mạ kẽm", "ma kem")):
            material_odoo = "black"

        if not tokens and not material_odoo:
            # Không có token kỹ thuật → dùng SequenceMatcher đơn giản (hàng phi tiêu chuẩn)
            from difflib import SequenceMatcher
            return SequenceMatcher(None, odoo_norm, cand_name).ratio() * 0.6

        # ─── Tính điểm khớp token ─────────────────────────────────────────────
        total_w = sum(w for w, _ in tokens)
        match_w = 0.0
        for weight, token in tokens:
            if token in cand_name:
                match_w += weight

        # Điểm vật liệu (bonus/penalty nhẹ — không penalty nặng vì MecSu hay bỏ qua)
        mat_score = 0.0
        if material_odoo:
            if material_odoo == "304":
                mat_score = 0.3 if any(k in cand_name for k in ("304", "inox", "ss304")) else -0.05
            elif material_odoo == "316":
                mat_score = 0.3 if "316" in cand_name else -0.05
            elif material_odoo == "black":
                mat_score = 0.3 if any(k in cand_name for k in ("đen", "carbon", "zinc", "kẽm")) else -0.05
            total_w += 0.3

        token_ratio = (match_w + max(0.0, mat_score)) / max(total_w, 0.001)
        return min(1.0, token_ratio)

    def _extract_search_terms(self, odoo_name):
        """Trích xuất cụm từ kỹ thuật tốt nhất để search mecsu.vn.

        Ưu tiên: kích thước (M16x50) > tiêu chuẩn (DIN933) > cấp độ bền (8.8).
        Tránh dùng tên tiếng Việt thuần vì MecSu hay dùng cách viết khác.
        """
        if not odoo_name:
            return odoo_name or ""

        parts = []

        # Kích thước M16x50
        dims = re.findall(r'M\d+(?:[x×]\d+(?:\.\d+)?)?', odoo_name, re.IGNORECASE)
        parts.extend(d.upper() for d in dims[:2])

        # Tiêu chuẩn DIN/ISO
        standards = re.findall(r'(?:DIN|ISO)\s*\d+', odoo_name, re.IGNORECASE)
        parts.extend(s.upper().replace(" ", "") for s in standards[:1])

        # Cấp độ bền
        grades = re.findall(r'\b(?:4\.8|8\.8|10\.9|12\.9)\b', odoo_name)
        parts.extend(grades[:1])

        if parts:
            return " ".join(parts)  # e.g. "M16x50 8.8"  hoặc  "M16x50 DIN933"

        # Fallback: lấy 3 từ cuối (thường chứa spec quan trọng hơn từ đầu)
        words = [w for w in odoo_name.split() if len(w) > 1]
        return " ".join(words[-3:]) if len(words) >= 2 else odoo_name

    def _mecsu_search_via_popup(self, query):
        """Tìm sản phẩm mecsu: GET /site?keyword= → popup button → quick-view → chi-tiet URL.

        Đây là flow đã được xác nhận hoạt động từ hlv_product_crawler/crawler_parsers.py:
        - Trang /site?keyword= SSR các popup button (a.mecsu-button-popup-lg)
        - Mỗi button chứa value="/product-quick-view/..." (server-side endpoint)
        - Quick-view page trả về HTML có link /chi-tiet/...
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []

        try:
            url = f"{MECSU_BASE}/site?keyword={urllib.parse.quote(query)}"
            html = self._mecsu_get(url)
        except Exception as e:
            _logger.warning("MecSu get /site?keyword=%s: %s", query, e)
            return []

        soup = BeautifulSoup(html, "html.parser")
        popup_btns = soup.select('a.mecsu-button-popup-lg[title="Thông số kỹ thuật"]')
        _logger.info("MecSu /site?keyword=%s → %d popup buttons", query, len(popup_btns))

        candidates = []
        seen_urls = set()
        for btn in popup_btns[:15]:
            quick_view_path = btn.get("value", "")
            if not quick_view_path or "product-quick-view" not in quick_view_path:
                continue
            quick_view_url = MECSU_BASE + quick_view_path
            try:
                qv_html = self._mecsu_get(quick_view_url)
                qv_soup = BeautifulSoup(qv_html, "html.parser")
                for link in qv_soup.select('a[href*="/chi-tiet/"]'):
                    href = link.get("href", "")
                    if not href:
                        continue
                    full_url = href if href.startswith("http") else MECSU_BASE + href
                    if full_url in seen_urls:
                        continue
                    # Lấy tên từ slug: /chi-tiet/bulong-thep-den-8-8-din933-m10x100.0054038
                    slug = href.split("/chi-tiet/")[-1]
                    slug_clean = re.sub(r"\.\d+$", "", slug)
                    name = slug_clean.replace("-", " ")
                    name = re.sub(r"\b(\d+) (\d)\b", r"\1.\2", name)
                    seen_urls.add(full_url)
                    candidates.append({"name": name, "url": full_url, "sku": ""})
                    break  # 1 chi-tiet per quick-view
            except Exception as e:
                _logger.warning("MecSu quick-view %s: %s", quick_view_url, e)

        return candidates

    def _mecsu_search(self, odoo_code, odoo_name, max_pages=2):
        """Tìm kiếm sản phẩm trên mecsu.vn qua popup button → quick-view flow."""
        candidates = []
        seen_urls = set()
        tech_query = self._extract_search_terms(odoo_name)

        def _add(items):
            for item in items:
                if item["url"] not in seen_urls:
                    seen_urls.add(item["url"])
                    candidates.append(item)

        # Chiến lược 1: technical terms (M10X100 8.8)
        if tech_query and tech_query.lower() != (odoo_name or "").lower():
            _add(self._mecsu_search_via_popup(tech_query))

        # Chiến lược 2: tên đầy đủ
        if odoo_name and len(candidates) < 3:
            _add(self._mecsu_search_via_popup(odoo_name))

        # Chiến lược 3: 3 từ cuối
        if not candidates and odoo_name:
            words = odoo_name.split()
            if len(words) > 3:
                _add(self._mecsu_search_via_popup(" ".join(words[-3:])))

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

    def _process_page(self, products, collection, max_count=None):
        """Xử lý một trang sản phẩm. Trả về số sản phẩm đã thực sự xử lý (qua filter)."""
        Line = self.env["hlv.doc.crawler.line"]
        processed = 0

        for product in products:
            if max_count is not None and processed >= max_count:
                break

            # Bộ lọc từ khóa (fallback — domain đã lọc ở ORM, check lại cho chắc)
            if not self._product_matches_filters(product):
                continue

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
                    tech_query = self._extract_search_terms(product.name)
                    _logger.info(
                        "MecSu [%s] SKU=%s | query='%s' | name='%s'",
                        self.name, sku, tech_query, product.name,
                    )
                    candidates = self._mecsu_search(sku, product.name)
                    _logger.info(
                        "MecSu [%s] SKU=%s | %d ứng viên",
                        self.name, sku, len(candidates),
                    )

                    # Tính điểm và chọn ứng viên tốt nhất
                    best = None
                    best_score = 0.0
                    score_log = []
                    for candidate in candidates:
                        score = self._mecsu_score(sku, product.name, candidate)
                        score_log.append((score, candidate.get("name", "")[:60]))
                        if score > best_score:
                            best_score = score
                            best = candidate

                    if score_log:
                        top = sorted(score_log, reverse=True)[:3]
                        _logger.info(
                            "MecSu [%s] SKU=%s | top scores: %s",
                            self.name, sku,
                            "; ".join(f"{s:.2f} – {n}" for s, n in top),
                        )

                    threshold = self.mecsu_similarity_threshold or 0.65
                    if not best or best_score < threshold:
                        debug_msg = (
                            f"Query: '{tech_query}' | {len(candidates)} ứng viên"
                            + (f" | Cao nhất: {best_score:.2f} – {best['name'][:50]}" if best else " | 0 ứng viên")
                        )
                        line.write({"status": "not_found", "error_msg": debug_msg})
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

        return processed

    def action_run(self):
        """Chạy crawler bắt đầu từ skip hiện tại. Nếu bật auto_next_page, tự động chạy hết."""
        import time as _time

        self.ensure_one()
        self.write({"state": "running", "last_run": fields.Datetime.now()})
        self._cr.commit()

        collection = self._get_rag_collection()
        current_skip = self.skip
        total_processed = 0
        total_pages = 0

        search_domain = self._build_search_domain()
        _logger.info("Crawler [%s] domain: %s", self.name, search_domain)

        while True:
            products = self.env["product.template"].search(
                search_domain,
                offset=current_skip,
                limit=self.limit,
            )
            if not products:
                break

            # Check max_products ceiling across pages
            remaining = None
            if self.use_max_products:
                remaining = self.max_products - total_processed
                if remaining <= 0:
                    break

            page_processed = self._process_page(products, collection, remaining)
            total_processed += page_processed
            total_pages += 1

            # Commit progress so UI shows partial results
            self._cr.commit()

            # Stop conditions
            if not self.auto_next_page:
                break
            if len(products) < self.limit:
                break  # last page
            if self.use_max_products and total_processed >= self.max_products:
                break

            # Advance to next page
            current_skip += self.limit
            self.write({"skip": current_skip})
            self._cr.commit()

            delay = max(1, self.page_delay or 1)
            _time.sleep(delay)

        self.write({"state": "done"})
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Crawler hoàn thành"),
                "message": _(
                    "Tổng %d trang  |  Xử lý: %d SP  |  Tìm thấy: %d  |  Không tìm thấy: %d  |  Lỗi: %d"
                )
                % (
                    total_pages,
                    total_processed,
                    self.found_count,
                    self.not_found_count,
                    self.error_count,
                ),
                "type": "success",
                "sticky": True,
            },
        }

    def action_next_page(self):
        """Tăng skip thêm limit rồi chạy trang tiếp theo."""
        self.ensure_one()
        self.write({"skip": self.skip + self.limit})
        return self.action_run()

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
