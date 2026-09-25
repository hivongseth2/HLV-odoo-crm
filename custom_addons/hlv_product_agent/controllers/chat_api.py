# -*- coding: utf-8 -*-
"""API cho khung chat trên /search_stock. Chạy dưới quyền chính tài khoản đang đăng
nhập: record rule chỉ cho mỗi tài khoản thấy hội thoại của mình.

Tài khoản dùng chung cho nhiều sale: trình duyệt gửi kèm sale_key của người đang
chat (người đó tự chọn một lần trên máy). Không có sale_key hợp lệ thì KHÔNG trả hội
thoại nào, bắt chọn người trước — đoán bừa là trộn tin của hai người vào một phiên.
"""
from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

from ..services import resolve_sale_identity


def _who(sale_key):
    """Người đang chat. Trả ``(identity, choices)``; identity None nghĩa là phải chọn.

    choices: danh sách để khung chat hiện nút chọn / đổi người; rỗng với tài khoản một
    người. Tài khoản một người được trả identity có key rỗng để khớp các cuộc cũ.
    """
    Session = request.env['hlv.product.chat.session']
    identities = Session.sale_identities(request.env.user)
    identity, shared = resolve_sale_identity(identities, sale_key)
    if not shared:
        return (dict(identity, key=False) if identity else {}), []
    choices = [{'key': item['key'], 'name': item['name']} for item in identities]
    return identity, choices


def _state(session, identity, choices, after_id=0):
    if identity is None:
        payload = {'session_id': False, 'busy': False, 'messages': [], 'identity_required': True}
    elif session:
        payload = session.client_state(after_id)
    else:
        payload = {'session_id': False, 'busy': False, 'messages': []}
    payload.update({
        'identity': {'key': identity.get('key'), 'name': identity.get('name')} if identity else None,
        'identity_choices': choices,
        'agent_online': request.env['hlv.product.agent'].is_any_online(),
    })
    return payload


class ProductChatApi(http.Controller):

    @http.route('/product_agent/chat/state', type='json', auth='user', methods=['POST'])
    def state(self, after_id=0, sale_key=None, **kw):
        """Tin mới hơn after_id của cuộc đang mở. Khung chat gọi định kỳ."""
        Session = request.env['hlv.product.chat.session']
        # Sale vẫn đang nhìn khung chat: nếu agent chết thì phải báo sớm, không để treo.
        Session.release_stale()
        identity, choices = _who(sale_key)
        session = Session.current_for_user(identity) if identity is not None else Session
        return _state(session, identity, choices, after_id)

    @http.route('/product_agent/chat/send', type='json', auth='user', methods=['POST'])
    def send(self, text='', images=None, after_id=0, sale_key=None, **kw):
        """Gửi một tin (chữ và/hoặc ảnh). Trả trạng thái mới, hoặc 'error' cho sale đọc."""
        Session = request.env['hlv.product.chat.session']
        identity, choices = _who(sale_key)
        if identity is None:
            return _state(Session, identity, choices)
        session = Session.current_for_user(identity) or Session.create_for_user(identity)
        try:
            session.post_user_message(text, images or [])
        except UserError as error:
            payload = _state(session, identity, choices, after_id)
            payload['error'] = str(error)
            return payload
        return _state(session, identity, choices, after_id)

    @http.route('/product_agent/chat/new', type='json', auth='user', methods=['POST'])
    def new(self, sale_key=None, **kw):
        """Kết thúc cuộc đang mở của người này, bắt đầu cuộc mới (Claude không nhớ cuộc cũ)."""
        Session = request.env['hlv.product.chat.session']
        identity, choices = _who(sale_key)
        if identity is None:
            return _state(Session, identity, choices)
        return _state(Session.start_new_for_user(identity), identity, choices)
