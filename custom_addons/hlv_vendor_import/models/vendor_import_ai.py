# -*- coding: utf-8 -*-
"""Claude duyệt ứng viên của các dòng file NCC — chạy nền, không trong request của người dùng.

Một file vài trăm dòng là vài lần gọi API, mỗi lần có thể cả phút: request "Đọc file" phải trả về ngay.
Giống trợ lý tạo mã (hlv_product_agent): sau commit mở một luồng có cursor riêng; cron vài phút một lần
vớt lần nhập bị bỏ dở (worker khởi động lại, luồng chết). Commit sau mỗi lô: lỗi giữa chừng không mất
các lô đã duyệt, bấm "Chạy lại AI" chỉ chạy phần còn chờ.

Dùng API key của trợ lý tạo mã (một chỗ cấu hình, một hoá đơn); model riêng trong Cài đặt → Mua hàng.
"""

import logging
import threading
from datetime import timedelta

from odoo import SUPERUSER_ID, api, fields, models
from odoo.modules.registry import Registry

from odoo.addons.hlv_product_agent.services.claude_api_payload import MODEL_CHOICES, request_extras
from odoo.addons.hlv_product_agent.services.claude_client import api_error_message, load_anthropic, make_client

from ..services.review_payload import (
    BATCH_SIZE, MAX_TOKENS, OUTPUT_SCHEMA, SYSTEM_PROMPT, VERDICT_MATCH, VERDICT_NONE, VERDICT_PROBABLE,
    parse_review, review_message,
)

_logger = logging.getLogger(__name__)

PARAM_MODEL = "hlv_vendor_import.ai_model"
# Ghép nhầm là đưa tồn / giá của hàng này sang hàng khác: dùng model giỏi nhất, suy nghĩ kỹ. Mỗi file
# chỉ vài lần gọi nên chi phí nhỏ.
DEFAULT_MODEL = "claude-opus-5-5"
EFFORT = "high"
REQUEST_TIMEOUT_SECONDS = 300
# Lần nhập "đang duyệt" mà quá ngần này không báo còn sống (mỗi lô một lần) là luồng đã chết.
STALE_MINUTES = 15


NO_KEY_MESSAGE = ("Chưa có Anthropic API key (Cài đặt → Tồn kho → Trợ lý tạo mã hàng). "
                  "Xác nhận tay, hoặc thêm key rồi bấm Chạy lại AI.")


class ReviewFailed(Exception):
    """Không duyệt tiếp được; thông điệp hiện trên lần nhập."""


class HlvVendorImportAi(models.AbstractModel):
    _name = "hlv.vendor.import.ai"
    _description = "Claude duyệt dòng file NCC"

    @api.model
    def config(self):
        model = self.env["ir.config_parameter"].sudo().get_param(PARAM_MODEL) or DEFAULT_MODEL
        return {
            "api_key": self.env["hlv.product.agent.api.runner"].config()["api_key"],
            "model": model if model in dict(MODEL_CHOICES) else DEFAULT_MODEL,
        }

    @api.model
    def queue(self, imports):
        """Xếp các lần nhập vào hàng chờ AI và chạy ngay trong luồng nền sau khi request commit.

        Phải đợi commit: luồng mở cursor riêng, trước commit nó chưa thấy các dòng vừa tạo.
        """
        if not self.config()["api_key"]:
            imports.write({"ai_state": "failed", "ai_error": NO_KEY_MESSAGE})
            return
        imports.write({"ai_state": "queued", "ai_error": False})
        dbname, ids = self.env.cr.dbname, imports.ids
        self.env.cr.postcommit.add(lambda: _start_thread(dbname, ids))

    @api.model
    def _cron_review(self):
        stale = fields.Datetime.now() - timedelta(minutes=STALE_MINUTES)
        imports = self.env["hlv.vendor.import"].search([
            "|", ("ai_state", "=", "queued"), "&", ("ai_state", "=", "running"), ("ai_claimed_at", "<", stale)])
        for import_id in imports.ids:
            self._review(import_id)

    def _claim(self, import_id):
        """Cầm lần nhập (đang chờ, hoặc đang chạy mà luồng cũ đã chết). Trả True nếu cầm được.

        UPDATE có điều kiện: luồng nền và cron cùng tới thì chỉ một bên cầm.
        """
        stale = fields.Datetime.now() - timedelta(minutes=STALE_MINUTES)
        self.env.cr.execute("""
            UPDATE hlv_vendor_import SET ai_state = 'running', ai_claimed_at = %s
             WHERE id = %s AND (ai_state = 'queued' OR (ai_state = 'running' AND ai_claimed_at < %s))
            RETURNING id
        """, (fields.Datetime.now(), import_id, stale))
        claimed = bool(self.env.cr.fetchone())
        self.env.cr.commit()
        self.env.invalidate_all()
        return claimed

    def _review(self, import_id):
        if not self._claim(import_id):
            return
        record = self.env["hlv.vendor.import"].browse(import_id)
        try:
            anthropic = load_anthropic()
            if not anthropic:
                raise ReviewFailed("Odoo chưa cài thư viện anthropic.")
            config = self.config()
            client = make_client(anthropic, config["api_key"], timeout=REQUEST_TIMEOUT_SECONDS)
            while True:
                lines = record.line_ids.filtered(lambda line: line.ai_state == "pending")[:BATCH_SIZE]
                if not lines:
                    break
                self._review_batch(anthropic, client, config["model"], record, lines)
                record.ai_claimed_at = fields.Datetime.now()
                self.env.cr.commit()
            record.write({"ai_state": "done", "ai_error": False})
            record.message_post(body="AI duyệt xong: %s khớp, %s có thể, %s không có sản phẩm bên mình." % (
                record.match_count, record.probable_count, record.none_count))
        except ReviewFailed as failure:
            self.env.cr.rollback()
            record.write({"ai_state": "failed", "ai_error": str(failure)})
        except Exception:  # noqa: BLE001 — lỗi lạ cũng phải hiện trên lần nhập, không để "đang duyệt" mãi
            self.env.cr.rollback()
            _logger.exception("VENDOR_IMPORT AI lỗi ở lần nhập %s", import_id)
            record.write({"ai_state": "failed", "ai_error": "Lỗi hệ thống khi AI duyệt, xem log Odoo."})
        self.env.cr.commit()

    def _review_batch(self, anthropic, client, model, record, lines):
        """Một lần gọi Claude cho một lô dòng; câu trả lời bị cắt (max_tokens) thì chia đôi lô."""
        rows = self.env["hlv.vendor.import.line"].review_rows(lines)
        stop_reason, results = self._ask_review(anthropic, client, model, record.partner_id.display_name,
                                                record.profile_id.brand, rows, record.name)
        if results is None and stop_reason == "max_tokens" and len(lines) > 1:
            half = len(lines) // 2
            self._review_batch(anthropic, client, model, record, lines[:half])
            self._review_batch(anthropic, client, model, record, lines[half:])
            return
        if results is None:
            raise ReviewFailed("Claude không trả lời trọn vẹn (%s) ở dòng %s." % (stop_reason, lines[0].row_no))
        for line in lines:
            self._write_result(line, results.get(line.id))

    @api.model
    def _ask_review(self, anthropic, client, model, vendor, brand, rows, label):
        """Một lần gọi Claude duyệt các dòng (review_payload.review_message) — dùng cho cả lần nhập file lẫn gợi ý khớp
        mã (vendor_code_suggest.py). Trả (stop_reason, {row: kết quả}); câu trả lời không trọn (max_tokens / refusal)
        → kết quả None. Lỗi API / JSON → ReviewFailed. label: ghi log."""
        try:
            response = client.beta.messages.create(
                model=model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": review_message(vendor, brand, rows)}],
                output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
                **request_extras(model),
            )
        except anthropic.APIError as error:
            _logger.warning("VENDOR_IMPORT Claude API lỗi", exc_info=True)
            raise ReviewFailed(api_error_message(anthropic, error))
        usage = response.usage
        _logger.info("VENDOR_IMPORT %s %s: %s dòng, in=%s out=%s stop=%s", label, response.model, len(rows),
                     usage.input_tokens, usage.output_tokens, response.stop_reason)
        if response.stop_reason in ("max_tokens", "refusal"):
            return response.stop_reason, None
        text = next((block.text for block in response.content if block.type == "text"), "")
        try:
            return response.stop_reason, parse_review(text, rows)
        except (ValueError, KeyError, TypeError):
            raise ReviewFailed("Câu trả lời của Claude không đúng dạng JSON.")

    @staticmethod
    def _write_result(line, result):
        """Ghi kết luận AI; dòng người dùng đã quyết định trong lúc AI chạy thì chỉ ghi phần của AI."""
        result = result or {"product_id": False, "verdict": VERDICT_NONE,
                            "reason": "AI không trả kết quả cho dòng này."}
        vals = {"ai_state": "done", "ai_verdict": result["verdict"], "ai_product_id": result["product_id"],
                "ai_reason": result["reason"]}
        if line.decision == "pending" and result["verdict"] in (VERDICT_MATCH, VERDICT_PROBABLE):
            vals.update(product_id=result["product_id"], decision="pending", match_source="ai")
        line.write(vals)


def _start_thread(dbname, import_ids):
    """Luồng duyệt các lần nhập. Không daemon: worker tắt sẽ đợi lô đang dở xong."""
    thread = threading.Thread(target=_review_in_thread, args=(dbname, import_ids),
                              name="hlv_vendor_import_ai", daemon=False)
    thread.start()
    return thread


def _review_in_thread(dbname, import_ids):
    """Thân luồng: cursor riêng (cursor của request không dùng chung luồng được)."""
    threading.current_thread().dbname = dbname
    try:
        with Registry(dbname).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            for import_id in import_ids:
                env["hlv.vendor.import.ai"]._review(import_id)
    except Exception:  # noqa: BLE001 — lỗi một luồng không được giết worker
        _logger.exception("VENDOR_IMPORT luồng AI chết")
