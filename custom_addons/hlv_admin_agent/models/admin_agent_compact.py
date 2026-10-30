# -*- coding: utf-8 -*-
"""Tóm tắt phần đầu cuộc chat dài thay vì quên (như "compact" của Claude Code).

Khi lịch sử API bị bỏ (cuộc quá dài, nghỉ quá lâu, đổi model / prompt), lượt mới chỉ mang theo
COLD_START_HISTORY_LIMIT tin chữ gần nhất. Tin cũ hơn mà chưa nằm trong bản tóm tắt thì giao model phụ
(rẻ) gộp vào bản tóm tắt của cuộc — giữ được ID khách / cơ hội / báo giá, giá đã chốt, việc đã ghi.
"""
import logging

from odoo import models

from odoo.addons.hlv_product_agent.models.product_agent_api_runner import TurnFailed
from odoo.addons.hlv_product_agent.models.product_chat_session import COLD_START_HISTORY_LIMIT
from odoo.addons.hlv_product_agent.services.claude_api_payload import reply_text, request_extras

_logger = logging.getLogger(__name__)

SUMMARY_MAX_TOKENS = 4000
MESSAGE_MAX_CHARS = 2000
# Đủ cho vài chục lượt; cuộc cực dài thì phần cũ nhất đã nằm trong bản tóm tắt trước.
TRANSCRIPT_MAX_CHARS = 80000
ROLE_LABELS = {'user': "Người dùng", 'assistant': "Trợ lý", 'event': "Hệ thống"}
SUMMARY_SYSTEM = """Em tóm tắt cuộc chat giữa một quản lý công ty Hoàng Long Vũ và trợ lý AI (tạo báo giá, cơ hội
trên MISA CRM, tra kho, tạo mã hàng), để trợ lý làm tiếp mà không cần đọc lại các tin cũ.

GIỮ NGUYÊN VĂN: tên khách kèm ID MISA, số / ID cơ hội (CH…) và báo giá (BG…), mã hàng, số lượng, giá đã
chốt, ngày. Ghi rõ: việc ĐÃ ghi lên MISA (dòng "Hệ thống: Đã tạo / Đã sửa…"), việc đang dở / chờ người
dùng xác nhận, yêu cầu và sở thích người dùng nêu trong cuộc, câu hỏi còn bỏ ngỏ.
Bỏ: chào hỏi, phần trợ lý giải thích cách tra. Gạch đầu dòng, tiếng Việt, tối đa khoảng 400 từ.
Có "Tóm tắt trước" thì gộp vào bản mới (một bản duy nhất), không lặp."""


class HlvAdminAgentCompact(models.AbstractModel):
    _name = 'hlv.admin.agent.compact'
    _description = "Tóm tắt cuộc chat dài của trợ lý quản trị"

    def refresh_summary(self, session, config, anthropic, client):
        """Gộp các tin sắp rơi khỏi ngữ cảnh vào bản tóm tắt của cuộc. Commit khi xong.

        Lỗi model phụ không làm hỏng lượt: giữ bản tóm tắt cũ, lượt vẫn chạy với tin gần nhất.
        """
        overflow = self._overflow(session)
        if not overflow:
            return
        session.progress = "Đang tóm tắt phần đầu cuộc chat..."
        self.env.cr.commit()
        transcript = "\n\n".join(
            "%s: %s" % (ROLE_LABELS[msg.role], msg.content[:MESSAGE_MAX_CHARS]) for msg in overflow
        )[-TRANSCRIPT_MAX_CHARS:]
        content = "Tóm tắt trước:\n%s\n\nPhần mới cần gộp:\n%s" % (session.summary or "(chưa có)", transcript)
        model = config['worker_model']
        params = dict(model=model, max_tokens=SUMMARY_MAX_TOKENS, system=SUMMARY_SYSTEM, **request_extras(model))
        Runner = self.env['hlv.product.agent.api.runner']
        try:
            response = Runner._request(anthropic, client, params, [{'role': 'user', 'content': content}],
                                       stale_ok=False)
            Runner._record_usage(session, response)
            summary = reply_text(response.to_dict(mode='json').get('content'))
            if not summary:
                raise TurnFailed("model phụ không trả bản tóm tắt")
        except TurnFailed as failure:
            _logger.warning("ADMIN_AGENT không tóm tắt được cuộc %s: %s", session.id, failure)
            return
        session.write({'summary': summary, 'summary_upto_id': overflow[-1].id})
        _logger.info("ADMIN_AGENT tóm tắt cuộc %s tới tin %s", session.id, overflow[-1].id)
        self.env.cr.commit()

    @staticmethod
    def _overflow(session):
        """Tin chữ sẽ rơi khỏi ngữ cảnh lượt này mà chưa có trong bản tóm tắt (cũ trước)."""
        claimed = session.message_ids.filtered(lambda m: session.claim_token and m.claim_token == session.claim_token)
        before = claimed[:1].id or float('inf')
        older = session.message_ids.filtered(
            lambda m: (session.summary_upto_id or 0) < m.id < before and m.content)
        # Tin user / assistant gần nhất đi kèm lượt (prompt_cold); chỉ phần trước đó cần tóm tắt.
        recent = older.filtered(lambda m: m.role in ('user', 'assistant'))[-COLD_START_HISTORY_LIMIT:]
        cutoff = recent[:1].id or float('inf')
        return older.filtered(lambda m: m.id < cutoff)
