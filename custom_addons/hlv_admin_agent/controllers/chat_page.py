# -*- coding: utf-8 -*-
"""Trang chat của trợ lý quản trị và API của nó.

Mọi route kiểm quyền "Trợ lý quản trị: Được dùng" TRƯỚC khi làm gì: trợ lý tạo được báo giá / cơ
hội / mã hàng trên MISA, auth='user' thôi là mọi nhân viên (kể cả tài khoản kho) vào được. Cuộc
chat chỉ tra trong các cuộc của chính tài khoản đang đăng nhập.
"""
from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import request

GROUP = 'hlv_admin_agent.group_admin_agent_user'
PAGE_URL = '/tro-ly-quan-tri'
MAX_NAME_CHARS = 80


def _check_access():
    if not request.env.user.has_group(GROUP):
        raise AccessError("Chỉ người có quyền Trợ lý quản trị mới dùng được trang này.")


def _ready():
    """Đã khai API key chưa — chưa thì trang báo ngay thay vì để tin chờ mãi."""
    return bool(request.env['hlv.admin.agent.config'].current().run_config()['api_key'])


def _state(session, after_id=0):
    payload = session.client_state(after_id) if session else {'session_id': False, 'busy': False, 'messages': []}
    payload['ready'] = _ready()
    return payload


class AdminAgentChat(http.Controller):

    @http.route(PAGE_URL, type='http', auth='user', methods=['GET'])
    def page(self, **kw):
        if not request.env.user.has_group(GROUP):
            return request.not_found()
        return request.render('hlv_admin_agent.chat_page', {'user_name': request.env.user.name})

    @http.route('/admin_agent/chat/sessions', type='json', auth='user', methods=['POST'])
    def sessions(self, **kw):
        """Cột trái: các cuộc chat của tài khoản này."""
        _check_access()
        return {'sessions': request.env['hlv.admin.chat.session'].sidebar_for_user()}

    @http.route('/admin_agent/chat/state', type='json', auth='user', methods=['POST'])
    def state(self, session_id=0, after_id=0, **kw):
        """Tin mới hơn after_id của một cuộc. Trang gọi định kỳ khi đang chờ trả lời."""
        _check_access()
        Session = request.env['hlv.admin.chat.session']
        # Người dùng vẫn đang nhìn trang: luồng chết thì phải báo sớm, không để treo.
        Session.release_stale()
        return _state(Session.owned(session_id), after_id)

    @http.route('/admin_agent/chat/send', type='json', auth='user', methods=['POST'])
    def send(self, session_id=0, text='', images=None, after_id=0, **kw):
        """Gửi một tin; chưa có cuộc (session_id rỗng) thì mở cuộc mới. Lỗi nhập trả trong 'error'."""
        _check_access()
        Session = request.env['hlv.admin.chat.session']
        created = not session_id
        session = Session.create({}) if created else Session.owned(session_id)
        if not session:
            return dict(_state(Session), error="Cuộc chat không còn.")
        try:
            session.post_user_message(text, images or [])
        except UserError as error:
            # Tin hỏng ở cuộc vừa mở: bỏ luôn cuộc rỗng, khỏi để rác ở cột trái. Kiểm tin chạy trước
            # mọi lệnh ghi nên cuộc chưa có tin nào.
            if created:
                session.sudo().unlink()
                session = Session
            return dict(_state(session, after_id), error=str(error))
        return _state(session, after_id)

    @http.route('/admin_agent/chat/rename', type='json', auth='user', methods=['POST'])
    def rename(self, session_id=0, name='', **kw):
        _check_access()
        session = request.env['hlv.admin.chat.session'].owned(session_id)
        name = ' '.join((name or '').split())[:MAX_NAME_CHARS]
        if session and name:
            session.sudo().name = name
        return {'ok': bool(session and name)}

    @http.route('/admin_agent/chat/delete', type='json', auth='user', methods=['POST'])
    def delete(self, session_id=0, **kw):
        """Xoá một cuộc. Cuộc đang chạy thì không: luồng đang chạy sẽ ghi vào bản ghi đã xoá."""
        _check_access()
        session = request.env['hlv.admin.chat.session'].owned(session_id)
        if not session or session.state == 'processing':
            return {'ok': False}
        session.sudo().unlink()
        return {'ok': True}
