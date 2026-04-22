# -*- coding: utf-8 -*-
"""Patch llm.thread:

1. Bump max_tokens cho output (default Anthropic 4096 → quá ngắn).
2. Sửa _process_llm_body để render đúng:
   - GIỮ NGUYÊN unicode emoji thay vì demojize thành ":package:"
   - Bật markdown2 extras: tables, fenced-code-blocks, strike, cuddled-lists
   → bảng GFM (`| col | col |`) render thành <table> đẹp.
"""
import logging

import emoji
import markdown2
from markupsafe import Markup

from odoo import models

_logger = logging.getLogger(__name__)

_MARKDOWN_EXTRAS = [
    "tables",
    "fenced-code-blocks",
    "strike",
    "cuddled-lists",
    "break-on-newline",
    "task_list",
]


class LLMThread(models.Model):
    _inherit = "llm.thread"

    # ── max_tokens override ───────────────────────────────────────────
    def _prepare_chat_kwargs(self, message_history, use_streaming):
        kwargs = super()._prepare_chat_kwargs(message_history, use_streaming)
        try:
            param = self.env['ir.config_parameter'].sudo().get_param(
                'hlv_dp.chat.max_tokens', '8192',
            )
            max_tokens = int(param)
        except Exception:
            max_tokens = 8192
        if max_tokens and 'max_tokens' not in kwargs:
            kwargs['max_tokens'] = max_tokens
        return kwargs

    # ── markdown rendering fix ────────────────────────────────────────
    def _process_llm_body(self, body):
        """Override: GIỮ unicode emoji + bật GFM tables.

        Module gốc dùng ``emoji.demojize`` → đổi 📦 thành ":package:" text
        (chữ thô không render được). Đồng thời ``markdown2.markdown(body)``
        không bật extra ``tables`` → bảng `| a | b |` ra raw. Sửa cả 2.
        """
        if not body or isinstance(body, Markup):
            return body
        # 1) Bảo đảm shortcode :xxx: nếu LLM lỡ output → quay lại emoji thật
        try:
            body = emoji.emojize(body, language='alias')
        except Exception:
            pass
        # 2) Render markdown với extras GFM
        try:
            return markdown2.markdown(body, extras=_MARKDOWN_EXTRAS)
        except Exception:
            _logger.warning("markdown2 render failed, fallback to plain", exc_info=True)
            return markdown2.markdown(body)
