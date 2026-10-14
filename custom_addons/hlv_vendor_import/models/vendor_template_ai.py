# -*- coding: utf-8 -*-
"""Claude đề xuất mẫu file NCC (services/template_prompt.py) — chạy ngay trong request "Đọc file", một lần gọi, chỉ khi
cần đề xuất mẫu (lần đầu nhận file của NCC, NCC đổi khung). Không có API key / AI lỗi / quá giờ thì giữ phần đoán theo
từ khoá — nhập file không bao giờ bị chặn vì AI.

Người bên mình vẫn xem lại mẫu ở bước "Xem lại cột"; ghi chú của AI hiện ngay đó.
"""

import logging

from odoo import api, models

from odoo.addons.hlv_product_agent.services.claude_api_payload import request_extras
from odoo.addons.hlv_product_agent.services.claude_client import api_error_message, load_anthropic, make_client

from ..services.template_prompt import MAX_TOKENS, OUTPUT_SCHEMA, SYSTEM_PROMPT, parse_template, template_message
from .import_utils import fix_two_tier

_logger = logging.getLogger(__name__)

# Người dùng đang đợi trang "Đọc file": nghĩ vừa phải, quá giờ thì thôi (dùng phần đoán theo từ khoá).
EFFORT = "medium"
REQUEST_TIMEOUT_SECONDS = 90


class HlvVendorTemplateAi(models.AbstractModel):
    _name = "hlv.vendor.import.template.ai"
    _description = "Claude đề xuất mẫu file NCC"

    @api.model
    def suggest(self, profile, grid, sheet_names=(), kept_headers=(), keep_header=False):
        """Ghi đề xuất của AI vào profile (dòng tiêu đề, vai trò cột, tiền tố, hãng, × 1000, bỏ dòng nhóm, ghi chú).

        kept_headers: tiêu đề các cột người đã chọn vai trò ở mẫu cũ (NCC đổi khung) — giữ, không để AI đổi. Tiền tố /
        hãng đã có (người khai, hoặc lấy từ mẫu khác của NCC) cũng giữ. keep_header: người vừa tự chọn dòng tiêu đề —
        AI chỉ đề xuất cột theo dòng đó. Trả True nếu đã áp đề xuất của AI."""
        config = self.env["hlv.vendor.import.ai"].config()
        anthropic = load_anthropic()
        if not config["api_key"] or not anthropic or not grid:
            return False
        header = (profile.header_row, profile.header_rows) if keep_header else None
        answer = self._ask(anthropic, config, profile, grid, list(sheet_names), header)
        if not answer:
            return False
        if header:
            answer.update(header_row=profile.header_row, header_rows=int(profile.header_rows))
        self._apply(profile, grid, answer, set(kept_headers))
        return True

    def _ask(self, anthropic, config, profile, grid, sheet_names, header):
        """Một lần gọi Claude. Trả kết quả parse_template, hoặc None (lỗi API / quá giờ / câu trả lời hỏng — đã log)."""
        client = make_client(anthropic, config["api_key"], timeout=REQUEST_TIMEOUT_SECONDS)
        message = template_message(profile.partner_id.display_name, sheet_names or [profile.sheet_name or "?"],
                                   profile.sheet_name, grid, header)
        try:
            response = client.beta.messages.create(
                model=config["model"],
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": message}],
                output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
                **request_extras(config["model"]),
            )
        except anthropic.APIError as error:
            _logger.warning("VENDOR_TEMPLATE_AI NCC %s: %s", profile.partner_id.id, api_error_message(anthropic, error))
            return None
        _logger.info("VENDOR_TEMPLATE_AI NCC %s %s: in=%s out=%s stop=%s", profile.partner_id.id, response.model,
                     response.usage.input_tokens, response.usage.output_tokens, response.stop_reason)
        if response.stop_reason in ("max_tokens", "refusal"):
            return None
        text = next((block.text for block in response.content if block.type == "text"), "")
        try:
            return parse_template(text, len(grid), max((len(row) for row in grid), default=0))
        except (ValueError, KeyError, TypeError):
            _logger.warning("VENDOR_TEMPLATE_AI NCC %s: câu trả lời không đúng dạng", profile.partner_id.id)
            return None

    @staticmethod
    def _apply(profile, grid, answer, kept_headers):
        profile.write({
            # AI hay cho dòng tầng dưới của tiêu đề hai tầng — mẫu tính từ tầng trên.
            "header_row": fix_two_tier(grid, answer["header_row"], answer["header_rows"]),
            "header_rows": str(answer["header_rows"]),
            "code_prefixes": profile.code_prefixes or answer["code_prefixes"] or False,
            "brand": profile.brand or answer["brand"] or False,
            "price_in_thousands": answer["price_in_thousands"],
            "skip_group_rows": answer["skip_group_rows"],
            "ai_note": answer["note"] or False,
        })
        # Dòng tiêu đề có thể vừa đổi: dựng lại cột theo chỗ mới rồi mới gán vai trò AI chọn.
        profile.refresh_columns(grid)
        for column in profile.column_ids:
            if column.header in kept_headers or column.col_index not in answer["roles"]:
                continue
            role, warehouse = answer["roles"][column.col_index]
            column.write({"role": role, "warehouse": warehouse or column.warehouse if role == "stock" else False})
