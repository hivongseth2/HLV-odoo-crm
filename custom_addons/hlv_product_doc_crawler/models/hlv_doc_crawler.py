import base64
import logging
import re

from markdownify import markdownify as md

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .crawler_scoring import gpt_qc_score

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

    # === Override: chạy lại SP đã có tài liệu ===
    override_existing = fields.Boolean(
        default=False,
        string="Chạy lại SP đã có tài liệu",
        help="Nếu bật, sẽ crawl lại và ghi đè tài liệu cho cả những sản phẩm đã có. "
             "Nếu tắt, bỏ qua sản phẩm đã có product.document từ crawler.",
    )

    # === GPT QC Scoring ===
    use_gpt_qc = fields.Boolean(
        default=False,
        string="Dùng GPT chấm điểm QC",
        help="Sau khi matching bằng thuật toán, dùng GPT kiểm tra lại kết quả. "
             "Giúp giảm false positive (sản phẩm khớp sai).",
    )
    gpt_model = fields.Selection(
        [
            ("gpt-4o-mini", "GPT-4o Mini (rẻ, nhanh)"),
            ("gpt-3.5-turbo", "GPT-3.5 Turbo"),
            ("gpt-4o", "GPT-4o"),
        ],
        default="gpt-4o-mini",
        string="Model GPT",
        help="Model GPT dùng để chấm điểm QC. Khuyến nghị gpt-4o-mini (rẻ nhất, đủ tốt).",
    )
    gpt_qc_threshold = fields.Float(
        default=0.6,
        string="Ngưỡng GPT QC",
        help="Điểm GPT tối thiểu để giữ kết quả. "
             "Nếu GPT chấm thấp hơn ngưỡng → đánh dấu not_found.",
    )
    gpt_qc_all_candidates = fields.Boolean(
        default=False,
        string="Gửi tất cả ứng viên cho GPT",
        help="Bật: GPT chấm tất cả ứng viên rồi chọn tốt nhất (chính xác hơn, tốn token hơn).\n"
             "Tắt: chỉ gửi ứng viên có token score cao nhất (tiết kiệm token).",
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

    # ─── Shared helpers ───────────────────────────────────────────────────────

    def _clean_html(self, html_content):
        """Xóa script/style và chuyển HTML → markdown."""
        if not html_content:
            return ""
        clean = re.sub(
            r"<(script|style)[^>]*>.*?</\1>", "", html_content, flags=re.DOTALL
        )
        return md(clean, heading_style="ATX", bullets="-", strip=["img"]).strip()

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

    def _ensure_product_document_pdf(self, product, sku, pdf_bytes):
        """Tạo hoặc cập nhật product.document (file .pdf) từ bytes PDF tải về."""
        attachment_name = f"{sku}_web.pdf"
        encoded = base64.b64encode(pdf_bytes).decode()

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
                {"datas": encoded, "mimetype": "application/pdf"}
            )
            return existing

        return self.env["product.document"].create(
            {
                "name": attachment_name,
                "datas": encoded,
                "mimetype": "application/pdf",
                "res_model": "product.template",
                "res_id": product.id,
            }
        )

    def _product_has_crawler_document(self, product):
        """Kiểm tra sản phẩm đã có tài liệu từ crawler (file *_web.md hoặc *_web.pdf)."""
        return bool(self.env["product.document"].search(
            [
                ("res_model", "=", "product.template"),
                ("res_id", "=", product.id),
                "|",
                ("name", "=like", "%_web.md"),
                ("name", "=like", "%_web.pdf"),
            ],
            limit=1,
        ))

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
        """Tạo ORM domain bao gồm cả keyword filters."""
        domain = [("default_code", "!=", False), ("default_code", "!=", "")]

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

        exclude = self._parse_keywords(self.exclude_keywords)
        for kw in exclude:
            domain += [("name", "not ilike", kw), ("default_code", "not ilike", kw)]

        return domain

    # ─── GPT QC helper ────────────────────────────────────────────────────────

    def _get_gpt_api_key(self):
        """Lấy OpenAI API key từ ir.config_parameter (key: openai.api_key)."""
        ICP = self.env["ir.config_parameter"].sudo()
        return ICP.get_param("openai.api_key", "")

    def _run_gpt_qc(self, odoo_name, candidate_name):
        """Chạy GPT QC scoring nếu được bật. Trả về dict hoặc None."""
        if not self.use_gpt_qc:
            return None
        api_key = self._get_gpt_api_key()
        if not api_key:
            _logger.warning("GPT QC bật nhưng thiếu API key (openai.api_key)")
            return None
        return gpt_qc_score(
            api_key, odoo_name, candidate_name,
            model=self.gpt_model or "gpt-4o-mini",
        )

    # ─── Processing dispatch ──────────────────────────────────────────────────

    def _process_page(self, products, collection, max_count=None):
        """Xử lý một trang sản phẩm. Trả về số sản phẩm đã thực sự xử lý."""
        Line = self.env["hlv.doc.crawler.line"]
        processed = 0

        for product in products:
            if max_count is not None and processed >= max_count:
                break

            if not self._product_matches_filters(product):
                continue

            # Skip sản phẩm đã có tài liệu nếu không bật override
            if not self.override_existing and self._product_has_crawler_document(product):
                _logger.info(
                    "Crawler [%s] SKU=%s: đã có tài liệu, bỏ qua (override=False)",
                    self.name, product.default_code,
                )
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
                    self._process_wc_product(product, sku, line, collection)
                elif self.source == "mecsu":
                    self._process_mecsu_product(product, sku, line, collection)
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

    # ─── Actions ──────────────────────────────────────────────────────────────

    def action_run(self):
        """Chạy crawler bắt đầu từ skip hiện tại."""
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

            remaining = None
            if self.use_max_products:
                remaining = self.max_products - total_processed
                if remaining <= 0:
                    break

            page_processed = self._process_page(products, collection, remaining)
            total_processed += page_processed
            total_pages += 1

            self._cr.commit()

            if not self.auto_next_page:
                break
            if len(products) < self.limit:
                break
            if self.use_max_products and total_processed >= self.max_products:
                break

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
