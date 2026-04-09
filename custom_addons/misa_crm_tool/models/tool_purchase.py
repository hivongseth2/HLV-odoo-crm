# -*- coding: utf-8 -*-
import json
import logging

from odoo import models

_logger = logging.getLogger(__name__)

# -- OpenAI function schema -------------------------------------------------

SCHEMA_SEARCH_PURCHASE_VOUCHER = {
    "type": "function",
    "name": "search_purchase_voucher",
    "description": (
        "Tìm kiếm chứng từ nhập kho mua hàng trong MISA theo diễn giải. "
        "Hỗ trợ tìm nhiều mã phân cách bởi dấu phẩy (VD: 'DH1255, DH1256')."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "journal_memo": {
                "type": "string",
                "description": "Diễn giải hoặc mã chứng từ (VD: DH1255, PO0012)",
            },
            "limit": {
                "type": "integer",
                "description": "Số kết quả tối đa (mặc định 20)",
            },
        },
        "required": ["journal_memo"],
        "additionalProperties": False,
    },
    "strict": True,
}


# -- Tool mixin -------------------------------------------------------------

class MisaCrmToolPurchase(models.AbstractModel):
    _inherit = 'misa.crm.tools'

    def _get_tool_map(self):
        tools = super()._get_tool_map()
        tools['search_purchase_voucher'] = {
            'schema': SCHEMA_SEARCH_PURCHASE_VOUCHER,
            'handler': self._tool_search_purchase_voucher,
        }
        return tools

    # -- handler -------------------------------------------------------------

    def _tool_search_purchase_voucher(self, args):
        journal_memo = args.get('journal_memo')
        limit = args.get('limit', 20)
        _logger.info(
            "🔍 [MISA TOOL] search_purchase_voucher — memo=%s", journal_memo,
        )

        if not journal_memo:
            return self._fail("Thiếu tham số 'journal_memo'")

        results = self._api().search_purchase_voucher(
            journal_memo, limit=limit,
        )
        return self._ok(
            message=f"Tìm thấy {len(results)} chứng từ",
            count=len(results),
            data=results,
        )
