# -*- coding: utf-8 -*-
"""Bước "ai" của lần kiểm: Claude dựng thành phần hai bên của từng liên kết rồi so, tìm cặp map nhầm.

Dùng API key của Trợ lý tạo mã hàng (Cài đặt → Tồn kho) như các module HLV khác — một chỗ cấu hình,
một hoá đơn. Mỗi lô commit riêng: lỗi giữa chừng không mất các lô đã kiểm, "Chạy lại AI" chỉ chạy phần còn chờ.
"""

import logging
import time

from odoo import models

from odoo.addons.hlv_product_agent.services.claude_api_payload import request_extras
from odoo.addons.hlv_product_agent.services.claude_client import api_error_message, load_anthropic, make_client

from ..services.match_payload import BATCH_SIZE, MAX_TOKENS, OUTPUT_SCHEMA, match_message, parse_match
from ..services.product_rules import VERDICT_PROBABLE
from .shopee_product_check import CheckFailed

_logger = logging.getLogger(__name__)

# So thành phần combo cần suy luận từng món (loại, model, thông số, số lượng): nghĩ kỹ.
EFFORT = "high"
REQUEST_TIMEOUT_SECONDS = 300
NO_KEY_MESSAGE = ("Chưa có Anthropic API key (Cài đặt → Tồn kho → Trợ lý tạo mã hàng). Thêm key rồi bấm "
                  "Chạy lại AI — dữ liệu Shopee đã lấy được giữ nguyên.")


class HlvShopeeProductCheck(models.Model):
    _inherit = "hlv.shopee.product.check"

    def _step_ai(self, deadline):
        anthropic = load_anthropic()
        if not anthropic:
            raise CheckFailed("Odoo chưa cài thư viện anthropic.")
        api_key = self.env["hlv.product.agent.api.runner"].config()["api_key"]
        if not api_key:
            raise CheckFailed(NO_KEY_MESSAGE)
        client = make_client(anthropic, api_key, timeout=REQUEST_TIMEOUT_SECONDS)
        # Prompt sửa trên Odoo (Prompt AI kiểm map nhầm) — đọc một lần cho cả lượt.
        system_prompt, _version = self.env["hlv.shopee.check.prompt"].current()
        while time.monotonic() < deadline:
            pending = self.line_ids.filtered(lambda line: line.ai_state == "pending")
            if not pending:
                self.step = "done"
                return
            shop = pending[0].shop_id
            self._review_batch(anthropic, client, system_prompt,
                               pending.filtered(lambda line: line.shop_id == shop)[:BATCH_SIZE])
            self.env.cr.commit()

    def _review_batch(self, anthropic, client, system_prompt, lines):
        """Một lần gọi Claude cho một lô; câu trả lời bị cắt (max_tokens) thì chia đôi lô."""
        pairs = [line.pair() for line in lines]
        stop_reason, results = self._ask(anthropic, client, system_prompt, lines[0].shop_id.name, pairs)
        if results is None and stop_reason == "max_tokens" and len(lines) > 1:
            half = len(lines) // 2
            self._review_batch(anthropic, client, system_prompt, lines[:half])
            self._review_batch(anthropic, client, system_prompt, lines[half:])
            return
        if results is None:
            raise CheckFailed("Claude không trả lời trọn vẹn (%s)." % stop_reason)
        for line in lines:
            # AI bỏ sót dòng thì để người xem, không coi là khớp.
            result = results.get(line.id) or {"verdict": VERDICT_PROBABLE, "reason": "AI không trả kết quả cho dòng này.",
                                              "shopee_contents": "", "odoo_contents": ""}
            line.write({"ai_state": "done", "ai_verdict": result["verdict"], "ai_reason": result["reason"],
                        "ai_shopee_contents": result["shopee_contents"], "ai_odoo_contents": result["odoo_contents"]})

    def _ask(self, anthropic, client, system_prompt, shop_name, pairs):
        """Trả (stop_reason, {row: kết quả}); câu trả lời không trọn (max_tokens / refusal) → kết quả None."""
        try:
            response = client.beta.messages.create(
                model=self.ai_model,
                max_tokens=MAX_TOKENS,
                system=system_prompt,
                messages=[{"role": "user", "content": match_message(shop_name, pairs)}],
                output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
                **request_extras(self.ai_model),
            )
        except anthropic.APIError as error:
            _logger.warning("SHOPEE_CHECK Claude API lỗi", exc_info=True)
            raise CheckFailed(api_error_message(anthropic, error))
        usage = response.usage
        _logger.info("SHOPEE_CHECK %s %s: %s cặp, in=%s out=%s stop=%s", self.id, response.model, len(pairs),
                     usage.input_tokens, usage.output_tokens, response.stop_reason)
        if response.stop_reason in ("max_tokens", "refusal"):
            return response.stop_reason, None
        text = next((block.text for block in response.content if block.type == "text"), "")
        try:
            return response.stop_reason, parse_match(text, {pair["row"] for pair in pairs})
        except (ValueError, KeyError, TypeError):
            raise CheckFailed("Câu trả lời của Claude không đúng dạng JSON.")
