# -*- coding: utf-8 -*-
"""Chạy các tool MISA mà Claude gọi tới (qua MCP server trên máy agent).

Tách khỏi model hội thoại vì đây là lớp tích hợp MISA, không phải logic hội thoại.
Mọi handler trả về dict có khoá 'status' để Claude phân biệt được found / not_found /
error — coi lỗi là "không tìm thấy" là đường tạo trùng.
"""
import logging

from odoo import models

_logger = logging.getLogger(__name__)

# Nhóm mặc định khi không tra được nhóm nào khớp (DANH MỤC KHÁC trên MISA).
FALLBACK_CATEGORY_ID = 2


class HlvProductAgentTools(models.AbstractModel):
    _name = 'hlv.product.agent.tools'
    _description = "Tool MISA cho trợ lý tạo mã hàng"

    def run(self, session, name, args):
        """Chạy một tool cho một cuộc hội thoại.

        Nhận: session (đang được xử lý), tên tool, dict tham số.
        Trả: dict kết quả, luôn có 'status'.
        """
        handler = {
            'search_product_misa': self._search_product,
            'create_product_misa': self._create_product,
            'update_product_misa': self._update_product,
            'get_category_info': self._get_category_info,
            'search_category_misa': self._search_category,
        }.get(name)
        if not handler:
            return {'status': 'error', 'message': "Tool %s chưa được hỗ trợ." % name}
        if not isinstance(args, dict):
            return {'status': 'error', 'message': "Tham số phải là object JSON."}
        return handler(session, args)

    def _misa_utils(self):
        return self.env['misa.api.utils'].sudo()

    # =========================================================================
    # TOOL ĐỌC
    # =========================================================================
    def _search_product(self, session, args):
        name = (args.get('name') or '').strip()
        code = (args.get('code') or '').strip()
        if not name and not code:
            return {'status': 'error', 'message': "Cần truyền name hoặc code để tìm."}
        try:
            products = self._misa_utils().search_product_by_name(
                name=name or None, code=code or None, limit=5,
            )
        except Exception as error:
            _logger.exception("PRODUCT_AGENT MISA search error")
            return {'status': 'error', 'message': str(error)}

        if not products:
            return {
                'status': 'not_found',
                'message': "Không tìm thấy trong MISA. MISA tìm theo kiểu chứa nguyên cụm, "
                           "nên từ khóa ngắn hơn (chỉ mã model, hoặc 2-3 từ chính) có thể ra kết quả.",
            }
        return {
            'status': 'found',
            'count': len(products),
            'data': products,
            'instruction': "So sánh kỹ loại, hãng và thông số cốt lõi — kể cả phần mô tả — "
                           "trước khi kết luận trùng.",
        }

    def _get_category_info(self, session, args):
        cat_id = args.get('category_id')
        if not cat_id:
            return {'status': 'error', 'message': "Thiếu category_id"}
        try:
            misa_utils = self._misa_utils()
            headers = misa_utils._get_cached_crm_headers()
            real_name = misa_utils._get_category_name_by_id(headers, cat_id)
        except Exception as error:
            _logger.exception("PRODUCT_AGENT MISA category info error")
            return {'status': 'error', 'message': str(error)}

        if not real_name:
            return {
                'status': 'not_found',
                'category_id': cat_id,
                'message': "Không có nhóm nào mang ID này. Dùng search_category_misa để tìm lại.",
            }
        return {'status': 'found', 'category_id': cat_id, 'category_name': real_name}

    def _search_category(self, session, args):
        name = (args.get('name') or '').strip()
        if not name:
            return {'status': 'error', 'message': "Thiếu tên nhóm"}
        try:
            misa_utils = self._misa_utils()
            headers = misa_utils._get_cached_crm_headers()
            cat_id = misa_utils._get_category_id_by_name(headers, name)
            real_name = misa_utils._get_category_name_by_id(headers, cat_id) if cat_id else None
        except Exception as error:
            _logger.exception("PRODUCT_AGENT MISA category search error")
            return {'status': 'error', 'message': str(error)}

        if cat_id:
            return {
                'status': 'found',
                'category_id': cat_id,
                'category_name': real_name or name,
                'message': "Dùng ID này khi tạo hàng.",
            }
        return {
            'status': 'not_found',
            'category_id': FALLBACK_CATEGORY_ID,
            'message': "Không tìm thấy nhóm này. Có thể dùng ID %s (DANH MỤC KHÁC) "
                       "hoặc tìm lại với từ khóa khác." % FALLBACK_CATEGORY_ID,
        }

    # =========================================================================
    # TOOL GHI — mỗi lần ghi thành công đều để lại ghi chú trong hội thoại, để sale
    # và quản lý thấy chính xác cái gì đã lên MISA, không phụ thuộc lời Claude kể.
    # =========================================================================
    def _create_product(self, session, args):
        code = args.get('code')
        name = args.get('name')
        try:
            misa_id = self._misa_utils().create_product_misa_raw(
                code=code,
                name=name,
                price=args.get('price') or 0,
                tax_percent=args.get('tax') or 0,
                unit_name=args.get('unit') or 'Cái',
                category_name=args.get('category') or 'Hàng hóa',
                product_type=args.get('type') or 'goods',
                cat_id=args.get('category_id') or False,
                price_pu=args.get('price_pu') or 0,
                description=args.get('description') or "",
            )
        except Exception as error:
            _logger.exception("PRODUCT_AGENT MISA create error")
            return {'status': 'error', 'message': "Lỗi tạo MISA: %s" % error}

        _logger.info("PRODUCT_AGENT %s tạo MISA %s - %s (id %s)",
                     session.user_id.login, code, name, misa_id)
        session.post_event("Đã tạo trên MISA: %s — %s (nhóm ID %s, MISA ID %s)" % (
            code, name, args.get('category_id'), misa_id))
        return {
            'status': 'success',
            'message': "Tạo thành công: %s" % name,
            'misa_id': misa_id,
            'code': code,
        }

    def _update_product(self, session, args):
        field = args.get('field')
        misa_id = args.get('misa_id')
        new_value = args.get('new_value')
        old_value = args.get('old_value')
        try:
            updated = self._misa_utils().update_product_field_misa(misa_id, field, new_value, old_value)
        except Exception as error:
            _logger.exception("PRODUCT_AGENT MISA update error")
            return {'status': 'error', 'message': "Lỗi cập nhật MISA: %s" % error}

        if not updated:
            return {'status': 'error', 'message': "Không cập nhật được %s cho MISA ID %s." % (field, misa_id)}
        _logger.info("PRODUCT_AGENT %s sửa MISA %s: %s '%s' -> '%s'",
                     session.user_id.login, misa_id, field, old_value, new_value)
        session.post_event("Đã sửa trên MISA (ID %s): %s «%s» → «%s»" % (
            misa_id, field, old_value, new_value))
        return {'status': 'success', 'message': "Đã cập nhật %s thành %s" % (field, new_value)}
