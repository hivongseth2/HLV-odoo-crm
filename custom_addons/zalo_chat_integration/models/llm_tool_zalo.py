# -*- coding: utf-8 -*-
"""
Bridge between zalo.llm.tools (abstract registry) and llm.tool (DB model).

Each Zalo tool is registered as an llm.tool implementation so it appears
in the "Công cụ AI" list view and can be discovered by the LLM framework.

NOTE: execute methods MUST have explicit parameter signatures (not **kwargs)
because llm.tool.execute() uses Pydantic to validate from method signature.
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class LLMToolZalo(models.Model):
    _inherit = "llm.tool"

    # -- Register 5 implementation types ------------------------------------
    @api.model
    def _get_available_implementations(self):
        implementations = super()._get_available_implementations()
        return implementations + [
            ("zalo_check_stock", "Zalo Check Stock"),
            ("zalo_search_product_odoo", "Zalo Search Product Odoo"),
            ("zalo_summarize_conversation", "Zalo Summarize Conversation"),
            ("zalo_create_quote", "Zalo Create Quotation"),
            ("zalo_send_message", "Zalo Send Message"),
        ]

    # -- Dispatch helper ----------------------------------------------------
    def _zalo_dispatch(self, tool_name, parameters):
        return self.env['zalo.llm.tools'].sudo().execute(tool_name, parameters)

    # -- Execution methods (explicit typed signatures) ----------------------

    def zalo_check_stock_execute(self, product: str) -> str:
        """Kiểm tra tồn kho sản phẩm theo từng kho."""
        return self._zalo_dispatch('zalo_check_stock', {'product': product})

    def zalo_search_product_odoo_execute(self, name: str) -> str:
        """Tìm kiếm sản phẩm trong Odoo."""
        return self._zalo_dispatch('zalo_search_product_odoo', {'name': name})

    def zalo_summarize_conversation_execute(self, conversation_id: int) -> str:
        """Tóm tắt hội thoại Zalo."""
        return self._zalo_dispatch('zalo_summarize_conversation', {
            'conversation_id': conversation_id,
        })

    def zalo_create_quote_execute(
        self,
        partner_id: int,
        products: str,
        note: str = '',
    ) -> str:
        """Tạo báo giá từ danh sách sản phẩm."""
        return self._zalo_dispatch('zalo_create_quote', {
            'partner_id': partner_id,
            'products': products,
            'note': note,
        })

    def zalo_send_message_execute(
        self,
        conversation_id: int,
        message: str,
    ) -> str:
        """Gửi tin nhắn Zalo tới khách hàng."""
        return self._zalo_dispatch('zalo_send_message', {
            'conversation_id': conversation_id,
            'message': message,
        })
