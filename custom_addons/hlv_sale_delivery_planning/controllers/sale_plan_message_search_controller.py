# -*- coding: utf-8 -*-
"""API cho panel "Tìm tin nhắn" của trang /sale_plan.

Tách rời như tính năng "Xem phiếu xuất kho":
    - Backend: chỉ file này (logic tìm dùng lại search_plan_messages của service —
      cùng domain với drawer tin nhắn bên điều phối).
    - UI: static/src/sale_plan_message_search/sale_plan_message_search.js.
    - Móc vào code cũ (đều có comment "TÌM TIN NHẮN"): 1 dòng import ở
      controllers/__init__.py, 1 thẻ <script src> + 1 listener 'sale_plan:open_order'
      trong sale_plan_controller.py.
"""

import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

# Sale tìm lại trao đổi cũ nên mặc định nhìn xa hơn drawer điều phối, nhưng vẫn
# chặn trần để ilike trên body không quét cả bảng mail.message.
_DEFAULT_LOOKBACK_DAYS = 365


class SalePlanMessageSearchController(http.Controller):

    @http.route('/api/sale_plan/search_messages', type='json', auth='user', methods=['POST'])
    def api_sale_plan_search_messages(self, search='', aliases=None, period='', date_from='',
                                      date_to='', limit=30, offset=0, **kwargs):
        try:
            result = request.env['hlv.delivery.planner.service'].search_plan_messages(
                search=search,
                aliases=aliases if isinstance(aliases, list) else [],
                limit=limit,
                offset=offset,
                days=_DEFAULT_LOOKBACK_DAYS,
                period=period or '',
                date_from=date_from or '',
                date_to=date_to or '',
            )
        except Exception as exc:
            _logger.exception('sale_plan search_messages error')
            return {'status': 'error', 'message': str(exc)}
        return {
            'status': 'success',
            'messages': result.get('messages', []),
            'has_more': bool(result.get('has_more')),
            'next_offset': result.get('next_offset', 0),
        }
