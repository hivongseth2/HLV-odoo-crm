# -*- coding: utf-8 -*-
import json
import logging

from odoo import models

_logger = logging.getLogger(__name__)

# -- OpenAI function schemas ------------------------------------------------

SCHEMA_GET_CATEGORY_INFO = {
    "type": "function",
    "name": "get_category_info",
    "description": (
        "Lấy tên chính xác của nhóm sản phẩm từ ID. "
        "Dùng để kiểm tra (double check) ID nhóm."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "category_id": {
                "type": "string",
                "description": "ID của nhóm sản phẩm (Ví dụ: 52, guid...)",
            },
        },
        "required": ["category_id"],
    },
    "strict": False,
}

SCHEMA_SEARCH_CATEGORY = {
    "type": "function",
    "name": "search_category_misa",
    "description": (
        "Tìm kiếm ID nhóm sản phẩm theo tên. "
        "Dùng khi người dùng yêu cầu nhóm cụ thể hoặc check nhóm."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Tên nhóm cần tìm (VD: Vật tư khí nén, Bảo hộ lao động...)",
            },
        },
        "required": ["name"],
    },
    "strict": False,
}


# -- Tool mixin -------------------------------------------------------------

class MisaCrmToolCategory(models.AbstractModel):
    _inherit = 'misa.crm.tools'

    def _get_tool_map(self):
        tools = super()._get_tool_map()
        tools['get_category_info'] = {
            'schema': SCHEMA_GET_CATEGORY_INFO,
            'handler': self._tool_get_category_info,
        }
        tools['search_category_misa'] = {
            'schema': SCHEMA_SEARCH_CATEGORY,
            'handler': self._tool_search_category,
        }
        return tools

    # -- handlers ------------------------------------------------------------

    def _tool_get_category_info(self, args):
        cat_id = args.get('category_id')
        _logger.info("ℹ️ [MISA TOOL] get_category_info — id=%s", cat_id)

        if not cat_id:
            return self._fail("Thiếu category_id")

        real_name = self._api().get_category_name(cat_id)
        return self._ok(
            category_id=cat_id,
            category_name=real_name,
            note="Hãy dùng tên này để trả lời User.",
        )

    def _tool_search_category(self, args):
        name = args.get('name')
        _logger.info("🔍 [MISA TOOL] search_category — name=%s", name)

        if not name:
            return self._fail("Thiếu tên nhóm")

        api = self._api()
        cat_id = api.search_category_by_name(name)

        if cat_id:
            real_name = api.get_category_name(cat_id) or name
            return self._ok(
                category_id=cat_id,
                category_name=real_name,
                message="Tìm thấy nhóm. Hãy dùng ID này để tạo sản phẩm.",
            )

        return json.dumps({
            "status": "not_found",
            "category_id": 2,
            "message": (
                "Không tìm thấy nhóm này. "
                "Có thể dùng ID 2 (DANH MỤC KHÁC) hoặc tìm lại với từ khóa khác."
            ),
        }, ensure_ascii=False)
