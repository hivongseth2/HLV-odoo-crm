# -*- coding: utf-8 -*-
"""Cron đọc nhóm Zalo bằng Claude → đề xuất giá / tồn kho cho báo giá NCC đang mở (hlv.zalo.proposal).

Mỗi lượt cron: nhóm đang ghi tin, có NCC, có tin mới từ phía NCC (không phải nhân viên mình) kể từ lượt trước → gom
đoạn hội thoại + các báo giá đang mở của NCC đó, gọi Claude MỘT lần cho nhóm. Không có báo giá đang mở thì chỉ dời mốc,
không gọi AI. Gọi Claude giống hlv_vendor_import (structured output JSON, cùng API key Trợ lý tạo mã hàng).
Mặc định TẮT (Cài đặt → Hỏi giá NCC → AI đọc Zalo) — bật mới tốn token.
"""

import base64
import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.addons.hlv_product_agent.services.claude_api_payload import MODEL_CHOICES, request_extras
from odoo.addons.hlv_product_agent.services.claude_client import api_error_message, load_anthropic, make_client
from odoo.addons.hlv_vendor_quotation.models.vendor_quote_utils import format_vn_number, local_date_text, price_incl_vat

from ..services.proposal_prompt import MAX_TOKENS, OUTPUT_SCHEMA, SYSTEM_PROMPT, parse_result, user_message

_logger = logging.getLogger(__name__)

PARAM_ENABLED = "hlv_vendor_zalo.ai_enabled"
PARAM_MODEL = "hlv_vendor_zalo.ai_model"
# Ghép nhầm là đưa giá hàng này sang hàng khác: model giỏi nhất. Chỉ gọi khi NCC có tin mới nên số lần gọi ít.
DEFAULT_MODEL = "claude-opus-5-5"
EFFORT = "medium"
REQUEST_TIMEOUT_SECONDS = 240
# Báo giá cũ hơn chừng này không đưa vào (NCC trả lời muộn hơn thế thì sale tự xử lý).
QUOTE_WINDOW_DAYS = 30
MAX_MESSAGES = 150
# Ảnh bảng giá / ảnh sản phẩm NCC gửi: vài ảnh gần nhất, mỗi ảnh ≤ 3,5MB (giới hạn ảnh của API là 5MB sau base64).
MAX_IMAGES = 4
IMAGE_MAX_BYTES = 3_500_000
IMAGE_MIMETYPES = ("image/jpeg", "image/png", "image/webp", "image/gif")
ROLES = {"vendor": "NCC", "staff": "NV", "unknown": "?"}


class ZaloAi(models.AbstractModel):
    _name = "hlv.zalo.ai"
    _description = "AI đọc nhóm Zalo NCC"

    @api.model
    def _config(self):
        params = self.env["ir.config_parameter"].sudo()
        model = params.get_param(PARAM_MODEL) or DEFAULT_MODEL
        return {
            "enabled": params.get_param(PARAM_ENABLED) == "True",
            "api_key": self.env["hlv.product.agent.api.runner"].config()["api_key"],
            "model": model if model in dict(MODEL_CHOICES) else DEFAULT_MODEL,
        }

    @api.model
    def _cron_read_groups(self):
        config = self._config()
        if not config["enabled"]:
            return
        anthropic = load_anthropic()
        if not anthropic or not config["api_key"]:
            _logger.warning("ZALO_AI bỏ qua: %s", "chưa cài thư viện anthropic" if not anthropic else "chưa có API key")
            return
        client = make_client(anthropic, config["api_key"], timeout=REQUEST_TIMEOUT_SECONDS)
        groups = self.env["hlv.zalo.group"].search([("enabled", "=", True), ("partner_id", "!=", False)])
        for group in groups:
            try:
                self._read_group(anthropic, client, config["model"], group)
                self.env.cr.commit()  # mỗi nhóm một lần: nhóm sau lỗi không mất đề xuất của nhóm trước
            except Exception:  # noqa: BLE001 — một nhóm lỗi (API, dữ liệu lạ) không chặn các nhóm khác
                self.env.cr.rollback()
                _logger.exception("ZALO_AI lỗi khi đọc nhóm %s", group.id)

    def _read_group(self, anthropic, client, model, group):
        Message = self.env["hlv.zalo.message"]
        last = Message.search([("group_id", "=", group.id)], order="id desc", limit=1)
        news = Message.search_count([("group_id", "=", group.id), ("id", ">", group.ai_last_message_id),
                                     ("is_self", "=", False), ("member_id.kind", "!=", "staff")])
        if not news:
            return
        quotes = self._open_quotes(group.partner_id)
        quote_rows = self._quote_rows(quotes)
        if quote_rows:
            since = min(quotes.mapped("create_date")) - timedelta(days=1)
            messages = Message.search([("group_id", "=", group.id), ("sent_at", ">=", since)],
                                      order="sent_at desc, id desc", limit=MAX_MESSAGES).sorted(lambda m: (m.sent_at, m.id))
            answer = self._ask_claude(anthropic, client, model, group, quote_rows, messages)
            if answer is None:
                return  # gọi AI lỗi: giữ mốc cũ, lượt sau đọc lại
            summary, result = answer
            Proposal = self.env["hlv.zalo.proposal"]
            for quote in quotes.filtered(lambda q: q.id in result):
                proposal, changed = Proposal._upsert_from_ai(group, quote, result[quote.id], summary, messages, model)
                if changed:
                    proposal._notify_sale()
        group.ai_last_message_id = last.id

    @api.model
    def _open_quotes(self, partner):
        """Báo giá NCC này còn nhận giá: đã gửi / đã báo, còn hạn sửa, chưa lên đơn mua hết, không quá QUOTE_WINDOW_DAYS."""
        since = fields.Datetime.now() - timedelta(days=QUOTE_WINDOW_DAYS)
        quotes = self.env["hlv.vendor.quote"].search([
            ("partner_id.commercial_partner_id", "=", partner.commercial_partner_id.id),
            ("state", "in", ("sent", "quoted")), ("create_date", ">=", since),
        ])
        return quotes.filtered(lambda q: q._is_open_for_vendor() and not q._fully_ordered())

    def _ask_claude(self, anthropic, client, model, group, quote_rows, messages):
        """Một lần gọi Claude cho cả nhóm. Trả (tóm tắt, {quote_id: [dòng]}); lỗi API / câu trả lời hỏng → None."""
        content = [{"type": "text", "text": user_message(
            group.partner_id.display_name, local_date_text(fields.Datetime.now()), quote_rows,
            self._message_rows(messages))}]
        content += self._image_blocks(messages)
        try:
            response = client.beta.messages.create(
                model=model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": content}],
                output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
                **request_extras(model),
            )
        except anthropic.APIError as error:
            _logger.warning("ZALO_AI nhóm %s: %s", group.id, api_error_message(anthropic, error))
            return None
        usage = response.usage
        _logger.info("ZALO_AI nhóm %s %s: %s báo giá, %s tin, in=%s out=%s stop=%s", group.id, response.model,
                     len(quote_rows), len(messages), usage.input_tokens, usage.output_tokens, response.stop_reason)
        if response.stop_reason in ("max_tokens", "refusal"):
            _logger.warning("ZALO_AI nhóm %s: Claude không trả lời trọn vẹn (%s)", group.id, response.stop_reason)
            return None
        text = next((block.text for block in response.content if block.type == "text"), "")
        try:
            return parse_result(text, quote_rows)
        except (ValueError, KeyError, TypeError):
            _logger.warning("ZALO_AI nhóm %s: câu trả lời không đúng JSON", group.id)
            return None

    @staticmethod
    def _quote_rows(quotes):
        rows = []
        for quote in quotes:
            lines = quote._vendor_lines().filtered(lambda l: not l.vendor_locked)
            rows.append({
                "id": quote.id, "name": quote.name, "inquiry": quote.inquiry_id.name or "",
                "sale": quote.inquiry_id.sale_code or "",
                "lines": [{
                    "id": line.id, "code": line.product_id.default_code or "", "name": line.name or line.product_id.name,
                    "qty": line.product_qty, "uom": line.product_uom_id.name or "",
                    "current": "hết hàng" if line.unavailable else (
                        f"{format_vn_number(round(price_incl_vat(line.price_unit, line.tax_rate)))} sau VAT"
                        if line.price_unit else ""),
                } for line in lines],
            })
        return [row for row in rows if row["lines"]]

    @staticmethod
    def _message_rows(messages):
        return [{
            "id": m.id, "at": local_date_text(m.sent_at, "%H:%M %d/%m/%Y"), "sender": m.member_id.name or "?",
            "role": ROLES.get(m.member_id.kind, "?"), "text": m.body or "",
            "quote_id": m.quote_message_id.id or 0, "quote_text": m.quote_text or "",
            "attachment": "ảnh" if m.kind == "image" else (f"file {m.media_title or ''}".strip() if m.media_url else ""),
        } for m in messages]

    @staticmethod
    def _image_blocks(messages):
        """Ảnh NCC gửi (đã tải về Odoo) — vài ảnh gần nhất, kèm dòng chữ nói ảnh thuộc tin số mấy."""
        blocks = []
        candidates = messages.filtered(lambda m: m.kind == "image" and m.member_id.kind != "staff")
        for message in candidates.sorted("id", reverse=True):
            attachment = message.attachment_ids.filtered(
                lambda a: a.mimetype in IMAGE_MIMETYPES and 0 < (a.file_size or 0) <= IMAGE_MAX_BYTES)[:1]
            if not attachment:
                continue
            blocks += [{"type": "text", "text": f"Ảnh trong tin #{message.id}:"},
                       {"type": "image", "source": {"type": "base64", "media_type": attachment.mimetype,
                                                    "data": base64.b64encode(attachment.raw).decode()}}]
            if len(blocks) >= 2 * MAX_IMAGES:
                break
        return blocks
