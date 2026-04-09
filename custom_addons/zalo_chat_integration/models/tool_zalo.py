# -*- coding: utf-8 -*-
"""
Zalo LLM tools — stock, product search, summarize, quote, send message.
Wraps existing methods from zalo_chat_integration models.
"""
import json
import logging
import re
import unicodedata

from odoo import models, tools, _

_logger = logging.getLogger(__name__)

# -- OpenAI function schemas ------------------------------------------------

SCHEMA_CHECK_STOCK = {
    "type": "function",
    "name": "zalo_check_stock",
    "description": (
        "Kiểm tra tồn kho sản phẩm theo từng kho (warehouse). "
        "Truyền mã sản phẩm (default_code) hoặc tên sản phẩm."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "product": {
                "type": "string",
                "description": "Mã sản phẩm (VD: FPD3-01) hoặc tên sản phẩm",
            },
        },
        "required": ["product"],
        "additionalProperties": False,
    },
    "strict": True,
}

SCHEMA_SEARCH_PRODUCT_ODOO = {
    "type": "function",
    "name": "zalo_search_product_odoo",
    "description": (
        "Tìm kiếm sản phẩm trong Odoo (tên, mã, alias). "
        "Trả về thông tin sản phẩm, giá, tồn kho."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Tên hoặc mã sản phẩm cần tìm",
            },
        },
        "required": ["name"],
        "additionalProperties": False,
    },
    "strict": True,
}

SCHEMA_SUMMARIZE_CONVERSATION = {
    "type": "function",
    "name": "zalo_summarize_conversation",
    "description": (
        "Tóm tắt nội dung hội thoại Zalo bằng AI. "
        "Truyền ID của zalo.chat.conversation."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "conversation_id": {
                "type": "integer",
                "description": "ID hội thoại Zalo (zalo.chat.conversation)",
            },
        },
        "required": ["conversation_id"],
        "additionalProperties": False,
    },
    "strict": True,
}

SCHEMA_CREATE_QUOTE = {
    "type": "function",
    "name": "zalo_create_quote",
    "description": (
        "Tạo báo giá (Sale Order) từ danh sách sản phẩm. "
        "Cần partner_id (khách hàng) và danh sách [{name, quantity, price_unit}]."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "partner_id": {
                "type": "integer",
                "description": "ID khách hàng (res.partner)",
            },
            "products": {
                "type": "string",
                "description": (
                    "JSON array sản phẩm: "
                    '[{"name": "Tên SP", "quantity": 1, "price_unit": 0}]. '
                    "price_unit=0 để lấy bảng giá mặc định."
                ),
            },
            "note": {
                "type": "string",
                "description": "Ghi chú cho báo giá (optional)",
            },
        },
        "required": ["partner_id", "products"],
        "additionalProperties": False,
    },
    "strict": True,
}

SCHEMA_SEND_ZALO_MESSAGE = {
    "type": "function",
    "name": "zalo_send_message",
    "description": (
        "Gửi tin nhắn văn bản tới khách hàng qua Zalo OA. "
        "Cần conversation_id hoặc zalo_user_id."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "conversation_id": {
                "type": "integer",
                "description": "ID hội thoại Zalo (zalo.chat.conversation)",
            },
            "message": {
                "type": "string",
                "description": "Nội dung tin nhắn gửi cho khách",
            },
        },
        "required": ["conversation_id", "message"],
        "additionalProperties": False,
    },
    "strict": True,
}


# -- Tool mixin -------------------------------------------------------------

class ZaloToolHandlers(models.AbstractModel):
    _inherit = 'zalo.llm.tools'

    def _get_tool_map(self):
        tools = super()._get_tool_map()
        tools['zalo_check_stock'] = {
            'schema': SCHEMA_CHECK_STOCK,
            'handler': self._tool_check_stock,
        }
        tools['zalo_search_product_odoo'] = {
            'schema': SCHEMA_SEARCH_PRODUCT_ODOO,
            'handler': self._tool_search_product_odoo,
        }
        tools['zalo_summarize_conversation'] = {
            'schema': SCHEMA_SUMMARIZE_CONVERSATION,
            'handler': self._tool_summarize_conversation,
        }
        tools['zalo_create_quote'] = {
            'schema': SCHEMA_CREATE_QUOTE,
            'handler': self._tool_create_quote,
        }
        tools['zalo_send_message'] = {
            'schema': SCHEMA_SEND_ZALO_MESSAGE,
            'handler': self._tool_send_message,
        }
        return tools

    # -- handlers ------------------------------------------------------------

    def _tool_check_stock(self, args):
        """Check stock per warehouse for a product."""
        product_query = args.get('product', '')
        if not product_query:
            return self._fail("Cần truyền 'product' (mã hoặc tên)")

        Product = self.env['product.product'].sudo()

        # Search by code first, then by name
        product = Product.search([('default_code', '=', product_query)], limit=1)
        if not product:
            product = Product.search([('default_code', 'ilike', product_query)], limit=1)
        if not product:
            product = Product.search([('name', 'ilike', product_query)], limit=5)

        if not product:
            return self._fail(f"Không tìm thấy sản phẩm: '{product_query}'")

        results = []
        whs = self.env['stock.warehouse'].sudo().search([])

        for p in product[:5]:
            wh_stock = {}
            for wh in whs:
                qty = p.with_context(warehouse=wh.id).qty_available
                wh_stock[wh.code or wh.name] = qty

            results.append({
                'name': p.name,
                'code': p.default_code or '',
                'price': p.lst_price,
                'qty_available': p.qty_available,
                'virtual_available': p.virtual_available,
                'stock_by_warehouse': wh_stock,
            })

        return self._ok(count=len(results), data=results)

    def _tool_search_product_odoo(self, args):
        """Search products in Odoo by name/code/alias."""
        name = args.get('name', '')
        if not name:
            return self._fail("Cần truyền 'name'")

        Product = self.env['product.product'].sudo()

        # 1. Alias match
        normalized = unicodedata.normalize('NFKD', name.strip().lower())
        normalized = ''.join(c for c in normalized if not unicodedata.combining(c))

        alias = self.env['product.alias'].sudo().search([
            ('normalized_alias', '=', normalized),
            ('active', '=', True),
        ], limit=1)

        candidates = Product.browse()
        if alias and alias.product_id:
            # Get all product.product variants for this template
            candidates = Product.search([
                ('product_tmpl_id', '=', alias.product_id.id)
            ], limit=5)

        # 2. Vector search (if config available)
        try:
            config = self.env['zalo.oa.config'].sudo().search([('active', '=', True)], limit=1)
            if config and config.gpt_api_key:
                vector_results = config.search_vector(name, 'product.product', limit=10, min_score=0.4)
                if vector_results:
                    vector_ids = [r[0] for r in vector_results]
                    candidates |= Product.browse(vector_ids)
        except Exception as e:
            _logger.warning("Vector search failed: %s", e)

        # 3. Text search
        text_results = Product.search([
            '|', ('name', 'ilike', name), ('default_code', 'ilike', name)
        ], limit=10)
        candidates |= text_results
        candidates = candidates.exists()

        if not candidates:
            return self._fail(f"Không tìm thấy sản phẩm: '{name}'")

        whs = self.env['stock.warehouse'].sudo().search([])
        results = []
        for p in candidates[:10]:
            wh_stock = {}
            for wh in whs:
                wh_stock[wh.code or wh.name] = p.with_context(warehouse=wh.id).qty_available

            results.append({
                'id': p.id,
                'name': p.name,
                'code': p.default_code or '',
                'price': p.lst_price,
                'category': p.categ_id.name,
                'unit': p.uom_id.name,
                'qty_available': p.qty_available,
                'stock_by_warehouse': wh_stock,
            })

        return self._ok(
            count=len(results),
            data=results,
            instruction="Hãy so sánh kỹ tên và mã. Chọn SP khớp nhất với yêu cầu khách."
        )

    def _tool_summarize_conversation(self, args):
        """Summarize a Zalo conversation using AI."""
        conv_id = args.get('conversation_id')
        if not conv_id:
            return self._fail("Cần truyền 'conversation_id'")

        conv = self.env['zalo.chat.conversation'].sudo().browse(int(conv_id))
        if not conv.exists():
            return self._fail(f"Không tìm thấy hội thoại ID={conv_id}")

        messages = conv.message_ids.sorted(key=lambda m: m.sent_date)[-50:]
        if not messages:
            return self._fail("Hội thoại chưa có tin nhắn để tóm tắt.")

        content_lines = []
        for msg in messages:
            sender = "Khách" if msg.direction == 'inbound' else "NV"
            content = msg.content or "[File/Image]"
            content_lines.append(f"{sender}: {content}")

        chat_content = "\n".join(content_lines)

        config = self.env['zalo.oa.config'].sudo().search([('active', '=', True)], limit=1)
        if not config or not config.gpt_api_key:
            return self._fail("Chưa cấu hình GPT API Key trong Zalo OA.")

        prompt = [
            {"role": "system", "content": (
                "Bạn là trợ lý AI quản lý khách hàng (CRM). "
                "Hãy đọc hội thoại và tóm tắt ngắn gọn:\n"
                "1. Nhu cầu/Vấn đề khách hàng\n"
                "2. Sản phẩm khách quan tâm\n"
                "3. Thái độ (Tích cực/Tiêu cực)\n"
                "4. Trạng thái (Đã chốt/Đang tư vấn/Khiếu nại)\n"
                "Trả lời bằng tiếng Việt, ngắn gọn."
            )},
            {"role": "user", "content": chat_content},
        ]

        summary = config._get_gpt_response(prompt)
        return self._ok(
            conversation_id=conv_id,
            customer=conv.zalo_user_name or '',
            summary=summary,
        )

    def _tool_create_quote(self, args):
        """Create a sale order from product list."""
        partner_id = args.get('partner_id')
        products_json = args.get('products', '[]')
        note = args.get('note', '')

        if not partner_id:
            return self._fail("Cần truyền 'partner_id'")

        partner = self.env['res.partner'].sudo().browse(int(partner_id))
        if not partner.exists():
            return self._fail(f"Không tìm thấy khách hàng ID={partner_id}")

        try:
            products_data = json.loads(products_json) if isinstance(products_json, str) else products_json
        except json.JSONDecodeError:
            return self._fail("'products' phải là JSON array hợp lệ")

        if not products_data:
            return self._fail("Danh sách sản phẩm rỗng")

        Product = self.env['product.product'].sudo()
        order_lines = []
        not_found = []

        for item in products_data:
            p_name = item.get('name', '')
            qty = item.get('quantity', 1)
            price_unit = item.get('price_unit', 0)

            # Search product
            product = Product.search([('default_code', '=', p_name)], limit=1)
            if not product:
                product = Product.search([
                    '|', ('name', 'ilike', p_name), ('default_code', 'ilike', p_name)
                ], limit=1)

            if product:
                line_vals = {
                    'product_id': product.id,
                    'product_uom_qty': qty,
                    'name': product.name,
                }
                if price_unit > 0:
                    line_vals['price_unit'] = price_unit
                order_lines.append((0, 0, line_vals))
            else:
                not_found.append(p_name)
                order_lines.append((0, 0, {
                    'display_type': 'line_note',
                    'name': f"SP chưa tìm thấy: {p_name} (SL: {qty})",
                }))

        so = self.env['sale.order'].sudo().create({
            'partner_id': partner.id,
            'order_line': order_lines,
            'note': note or 'Tạo từ Zalo AI Tool',
        })

        return self._ok(
            message=f"Đã tạo báo giá {so.name}",
            order_id=so.id,
            order_name=so.name,
            not_found=not_found,
        )

    def _tool_send_message(self, args):
        """Send a text message via Zalo OA."""
        conv_id = args.get('conversation_id')
        message = args.get('message', '')

        if not conv_id:
            return self._fail("Cần truyền 'conversation_id'")
        if not message:
            return self._fail("Cần truyền 'message'")

        conv = self.env['zalo.chat.conversation'].sudo().browse(int(conv_id))
        if not conv.exists():
            return self._fail(f"Không tìm thấy hội thoại ID={conv_id}")

        # Create outbound message record
        msg = self.env['zalo.chat.message'].sudo().create({
            'conversation_id': conv.id,
            'content': message,
            'direction': 'outbound',
            'message_type': 'text',
        })

        # Send via Zalo API
        try:
            msg.action_send()
        except Exception as e:
            return self._fail(f"Gửi tin nhắn thất bại: {str(e)}")

        return self._ok(
            message=f"Đã gửi tin nhắn tới {conv.zalo_user_name or conv.zalo_user_id}",
            message_id=msg.id,
        )
