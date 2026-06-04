# -*- coding: utf-8 -*-
import json
import logging

from odoo import models

_logger = logging.getLogger(__name__)

# -- OpenAI function schemas ------------------------------------------------

SCHEMA_SEARCH_PRODUCT = {
    "type": "function",
    "name": "search_product_misa",
    "description": (
        "Search to see if a product already exists in the system "
        "using its name before creating a new one."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Product name or keyword (e.g., Khoan FPD3, Bulong M12)",
            },
        },
        "required": ["name"],
        "additionalProperties": False,
    },
    "strict": True,
}

SCHEMA_CREATE_PRODUCT = {
    "type": "function",
    "name": "create_product_misa",
    "description": (
        "Tạo sản phẩm mới vào hệ thống. "
        "CHỈ GỌI KHI NGƯỜI DÙNG ĐÃ XÁC NHẬN 'OK' HOẶC 'ĐỒNG Ý'."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Mã sản phẩm (Viết liền, in hoa, không dấu)",
            },
            "name": {
                "type": "string",
                "description": "Tên sản phẩm chuẩn hóa đầy đủ",
            },
            "price": {
                "type": "number",
                "description": "Giá bán đề xuất (VNĐ). Mặc định 0.",
            },
            "price_pu": {
                "type": "number",
                "description": "Giá mua (VNĐ). Mặc định 0.",
            },
            "tax": {
                "type": "number",
                "description": "Thuế VAT (thường là 8 hoặc 10)",
            },
            "unit": {
                "type": "string",
                "description": "Đơn vị tính (Cái, Bộ, Hộp, Chai...)",
            },
            "category": {
                "type": "string",
                "description": "Tên nhóm hàng (Lấy từ file category.json)",
            },
            "category_id": {
                "type": "integer",
                "description": (
                    "ID nhóm hàng (Tra cứu từ file category.json)"
                ),
            },
            "type": {
                "type": "string",
                "enum": ["goods", "service", "finished_product"],
                "description": "Loại hàng hóa (Mặc định 'goods')",
            },
            "Description": {
                "type": "string",
                "description": "Mô tả sản phẩm trên MISA CRM. Có thể truyền chuỗi JSON, ví dụ: {\"Vật liệu\" : \"Thép\"}",
            },
        },
        "required": [
            "code", "name", "price", "tax", "unit",
            "category", "category_id", "type", "price_pu",
        ],
        "additionalProperties": False,
    },
    "strict": True,
}

SCHEMA_UPDATE_PRODUCT = {
    "type": "function",
    "name": "update_product_misa",
    "description": (
        "Cập nhật thông tin sản phẩm trên MISA: tên, mã, mô tả, giá bán cố định, "
        "giá mua, giá bán lẻ, thuế. Cần có misa_id của sản phẩm."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "misa_id": {
                "type": "string",
                "description": "MISA product ID (GUID)",
            },
            "field": {
                "type": "string",
                "enum": ["name", "code", "Description", "unit_price_fixed", "purchased_price", "unit_price", "tax","custom_field_16"],
                "description": "Trường cần cập nhật: name=tên, code=mã, Description=mô tả sản phẩm, unit_price_fixed=giá bán cố định, purchased_price=giá mua, unit_price=giá bán lẻ (gồm VAT), tax=thuế GTGT (truyền % VD: 10, 8), custom_field_16=Đơn giá mua bắt buộc",
            },
            "new_value": {
                "type": "string",
                "description": "Giá trị mới",
            },
            "old_value": {
                "type": "string",
                "description": "Giá trị cũ (để đối chứng)",
            },
        },
        "required": ["misa_id", "field", "new_value", "old_value"],
        "additionalProperties": False,
    },
    "strict": True,
}


# -- Tool mixin -------------------------------------------------------------

class MisaCrmToolProduct(models.AbstractModel):
    _inherit = 'misa.crm.tools'

    def _get_tool_map(self):
        tools = super()._get_tool_map()
        tools['search_product_misa'] = {
            'schema': SCHEMA_SEARCH_PRODUCT,
            'handler': self._tool_search_product,
        }
        tools['create_product_misa'] = {
            'schema': SCHEMA_CREATE_PRODUCT,
            'handler': self._tool_create_product,
        }
        tools['update_product_misa'] = {
            'schema': SCHEMA_UPDATE_PRODUCT,
            'handler': self._tool_update_product,
        }
        return tools

    # -- handlers ------------------------------------------------------------

    def _tool_search_product(self, args):
        name = args.get('name')
        code = args.get('code')
        _logger.info("🔍 [MISA TOOL] search_product — name=%s, code=%s", name, code)

        products = self._api().search_product(name=name, code=code, limit=5)
        if not products:
            return self._fail(
                "Không tìm thấy trong DB. Hãy thử từ khóa ngắn gọn hơn hoặc tìm theo Mã Model."
            )
        return self._ok(
            count=len(products),
            data=products,
            instruction=(
                "Hãy so sánh kỹ Tên và Mã. "
                "Nếu trùng khớp -> Báo đã có. "
                "Nếu khác -> Đề xuất tạo mới."
            ),
        )

    def _tool_create_product(self, args):
        _logger.info("🆕 [MISA TOOL] create_product — %s", args.get('code'))

        misa_id = self._api().create_product(
            code=args.get('code'),
            name=args.get('name'),
            price=args.get('price', 0),
            tax_percent=args.get('tax', 10),
            unit_name=args.get('unit', 'Cái'),
            category_name=args.get('category', 'Hàng hóa'),
            product_type=args.get('type', 'goods'),
            cat_id=args.get('category_id', False),
            price_pu=args.get('price_pu', 0),
            description=args.get('Description') or args.get('description') or "",
        )
        return self._ok(
            message=f"Tạo thành công sản phẩm: {args.get('name')}",
            misa_id=misa_id,
            code=args.get('code'),
        )

    def _tool_update_product(self, args):
        misa_id = args.get('misa_id')
        field = args.get('field')
        new_value = args.get('new_value')
        old_value = args.get('old_value')
        _logger.info(
            "✏️ [MISA TOOL] update_product — id=%s field=%s",
            misa_id, field,
        )

        ok = self._api().update_product_field(
            misa_id, field, new_value, old_value,
        )
        if ok:
            return self._ok(
                message=f"Đã cập nhật {field} thành '{new_value}'",
            )
        return self._fail(f"Không thể cập nhật {field} cho MISA ID {misa_id}")
