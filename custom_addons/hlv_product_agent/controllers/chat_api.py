# -*- coding: utf-8 -*-
"""API cho khung chat trên /search_stock. Chạy dưới quyền chính sale đang đăng nhập:
record rule chỉ cho mỗi người thấy hội thoại của mình."""
from odoo import http
from odoo.exceptions import UserError
from odoo.http import request


def _state(session, after_id=0):
    payload = session.client_state(after_id) if session else {
        'session_id': False, 'busy': False, 'messages': [],
    }
    payload['agent_online'] = request.env['hlv.product.agent'].is_any_online()
    return payload


class ProductChatApi(http.Controller):

    @http.route('/product_agent/chat/state', type='json', auth='user', methods=['POST'])
    def state(self, after_id=0, **kw):
        """Tin mới hơn after_id của cuộc đang mở. Khung chat gọi định kỳ."""
        Session = request.env['hlv.product.chat.session']
        # Sale vẫn đang nhìn khung chat: nếu agent chết thì phải báo sớm, không để treo.
        Session.release_stale()
        return _state(Session.current_for_user(), after_id)

    @http.route('/product_agent/chat/send', type='json', auth='user', methods=['POST'])
    def send(self, text='', images=None, after_id=0, **kw):
        """Gửi một tin (chữ và/hoặc ảnh). Trả trạng thái mới, hoặc 'error' cho sale đọc."""
        Session = request.env['hlv.product.chat.session']
        session = Session.current_for_user() or Session.create({})
        try:
            session.post_user_message(text, images or [])
        except UserError as error:
            payload = _state(session, after_id)
            payload['error'] = str(error)
            return payload
        return _state(session, after_id)

    @http.route('/product_agent/chat/new', type='json', auth='user', methods=['POST'])
    def new(self, **kw):
        """Kết thúc cuộc đang mở, bắt đầu cuộc mới (Claude không nhớ cuộc cũ)."""
        return _state(request.env['hlv.product.chat.session'].start_new_for_user())
