# -*- coding: utf-8 -*-
"""Thực thi các tool MISA mà AI gọi tới.

Tách khỏi model session vì đây là lớp tích hợp MISA, không phải logic hội thoại.
Mọi hàm ở đây trả về **chuỗi JSON** để nhét thẳng vào ``function_call_output``.
"""
import json
import logging

from odoo import models

from ..services import READ_ONLY_TOOLS

_logger = logging.getLogger(__name__)

# Nhóm mặc định khi không tra được nhóm nào khớp (DANH MỤC KHÁC trên MISA).
FALLBACK_CATEGORY_ID = 2


def _json(payload):
    return json.dumps(payload, ensure_ascii=False, default=str)


class HlvChatgptToolExecutor(models.AbstractModel):
    _name = 'hlv.chatgpt.tool.executor'
    _description = 'Thực thi tool MISA cho Chat AI'

    # =========================================================================
    # ĐIỀU PHỐI
    # =========================================================================
    def run_tool_call(self, tool_call, cache=None):
        """Chạy một function call và dựng item kết quả trả về cho OpenAI.

        Nhận: dict ``{'call_id', 'name', 'arguments'}`` (arguments là chuỗi JSON),
        và ``cache`` dùng chung trong một lượt hội thoại.
        Trả: dict ``{'type': 'function_call_output', 'call_id', 'output'}``,
        ``output`` luôn là chuỗi JSON kể cả khi lỗi.
        """
        name = tool_call.get('name') or ''
        args = self._parse_arguments(tool_call.get('arguments'))
        if args is None:
            return self._output(tool_call, _json({
                'status': 'error',
                'message': "Tham số không phải JSON hợp lệ. Hãy gọi lại tool với JSON đúng định dạng.",
            }))

        cache_key = (name, json.dumps(args, sort_keys=True, ensure_ascii=False, default=str))
        if cache is not None and cache_key in cache:
            if name in READ_ONLY_TOOLS:
                # Trả lại đúng kết quả cũ thay vì báo lỗi: AI vẫn có dữ liệu để trả lời,
                # mà không phải gọi MISA thêm lần nữa.
                return self._output(tool_call, cache[cache_key])
            return self._output(tool_call, _json({
                'status': 'already_executed',
                'message': "Lệnh ghi này đã chạy trong lượt hiện tại. Không gọi lại; "
                           "hãy dùng kết quả trước đó để trả lời người dùng.",
            }))

        handler = self._tool_handlers().get(name)
        if not handler:
            return self._output(tool_call, _json({
                'status': 'error',
                'message': "Function %s chưa được hỗ trợ." % name,
            }))

        result = handler(args)
        if cache is not None:
            cache[cache_key] = result
        return self._output(tool_call, result)

    def _tool_handlers(self):
        return {
            'search_product_misa': self._search_product,
            'create_product_misa': self._create_product,
            'update_product_misa': self._update_product,
            'get_category_info': self._get_category_info,
            'search_category_misa': self._search_category,
        }

    @staticmethod
    def _parse_arguments(raw_args):
        """Đổi arguments của OpenAI thành dict. Trả None nếu không parse được."""
        if isinstance(raw_args, dict):
            return raw_args
        try:
            parsed = json.loads(raw_args or '{}')
        except (TypeError, ValueError):
            _logger.warning("Arguments cua tool khong phai JSON: %r", raw_args)
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _output(tool_call, output_str):
        return {
            'type': 'function_call_output',
            'call_id': tool_call.get('call_id'),
            'output': output_str,
        }

    def _misa_utils(self):
        return self.env['misa.api.utils'].sudo()

    # =========================================================================
    # CÁC TOOL
    # =========================================================================
    def _search_product(self, args):
        name = (args.get('name') or '').strip()
        code = (args.get('code') or '').strip()
        if not name and not code:
            return _json({'status': 'error', 'message': "Cần truyền name hoặc code để tìm."})

        try:
            products = self._misa_utils().search_product_by_name(
                name=name or None, code=code or None, limit=5,
            )
        except Exception as error:
            _logger.exception("MISA search error")
            return _json({'status': 'error', 'message': str(error)})

        if not products:
            return _json({
                'status': 'not_found',
                'message': "Không tìm thấy trong MISA. MISA tìm theo kiểu chứa nguyên cụm, "
                           "nên hãy thử lại với từ khóa ngắn hơn (chỉ mã model, hoặc 2-3 từ khóa chính) "
                           "trước khi kết luận là chưa có sản phẩm.",
            })

        return _json({
            'status': 'found',
            'count': len(products),
            'data': products,
            'instruction': "So sánh kỹ Tên và Mã. Trùng khớp thì báo đã có. Khác thì đề xuất tạo mới.",
        })

    def _create_product(self, args):
        try:
            misa_id = self._misa_utils().create_product_misa_raw(
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
        except Exception as error:
            _logger.exception("MISA create error")
            return _json({'status': 'error', 'message': "Lỗi tạo MISA: %s" % error})

        return _json({
            'status': 'success',
            'message': "Tạo thành công sản phẩm: %s" % args.get('name'),
            'misa_id': misa_id,
            'code': args.get('code'),
        })

    def _update_product(self, args):
        field = args.get('field')
        misa_id = args.get('misa_id')
        new_value = args.get('new_value')
        try:
            updated = self._misa_utils().update_product_field_misa(
                misa_id, field, new_value, args.get('old_value'),
            )
        except Exception as error:
            _logger.exception("MISA update error")
            return _json({'status': 'error', 'message': "Lỗi cập nhật MISA: %s" % error})

        if updated:
            return _json({
                'status': 'success',
                'message': "Đã cập nhật %s thành %s" % (field, new_value),
            })
        return _json({
            'status': 'error',
            'message': "Không cập nhật được %s cho MISA ID %s." % (field, misa_id),
        })

    def _get_category_info(self, args):
        cat_id = args.get('category_id')
        if not cat_id:
            return _json({'status': 'error', 'message': "Thiếu category_id"})

        try:
            misa_utils = self._misa_utils()
            headers = misa_utils._get_cached_crm_headers()
            real_name = misa_utils._get_category_name_by_id(headers, cat_id)
        except Exception as error:
            _logger.exception("MISA category info error")
            return _json({'status': 'error', 'message': str(error)})

        if not real_name:
            return _json({
                'status': 'not_found',
                'category_id': cat_id,
                'message': "Không có nhóm nào mang ID này. Hãy dùng search_category_misa để tìm lại.",
            })
        return _json({
            'status': 'found',
            'category_id': cat_id,
            'category_name': real_name,
            'note': "Dùng đúng tên này khi trả lời người dùng.",
        })

    def _search_category(self, args):
        name = (args.get('name') or '').strip()
        if not name:
            return _json({'status': 'error', 'message': "Thiếu tên nhóm"})

        try:
            misa_utils = self._misa_utils()
            headers = misa_utils._get_cached_crm_headers()
            cat_id = misa_utils._get_category_id_by_name(headers, name)
            real_name = misa_utils._get_category_name_by_id(headers, cat_id) if cat_id else None
        except Exception as error:
            _logger.exception("MISA category search error")
            return _json({'status': 'error', 'message': str(error)})

        if cat_id:
            return _json({
                'status': 'found',
                'category_id': cat_id,
                'category_name': real_name or name,
                'message': "Dùng ID này khi tạo sản phẩm.",
            })
        return _json({
            'status': 'not_found',
            'category_id': FALLBACK_CATEGORY_ID,
            'message': "Không tìm thấy nhóm này. Có thể dùng ID %s (DANH MỤC KHÁC) "
                       "hoặc tìm lại với từ khóa khác." % FALLBACK_CATEGORY_ID,
        })
