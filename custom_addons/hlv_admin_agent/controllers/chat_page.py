# -*- coding: utf-8 -*-
"""Trang chat của trợ lý quản trị và API của nó.

Mọi route kiểm quyền "Trợ lý quản trị: Được dùng" TRƯỚC khi làm gì: trợ lý tạo được báo giá / cơ
hội / mã hàng trên MISA, auth='user' thôi là mọi nhân viên (kể cả tài khoản kho) vào được. Cuộc
chat chỉ tra trong các cuộc của chính tài khoản đang đăng nhập.
"""
from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import request

from odoo.addons.hlv_product_agent.services.claude_api_payload import MODEL_CHOICES

from ..services.personal import MEMORY_KINDS

GROUP = 'hlv_admin_agent.group_admin_agent_user'
MANAGER_GROUP = 'hlv_admin_agent.group_admin_agent_manager'
PAGE_URL = '/tro-ly-quan-tri'
MAX_NAME_CHARS = 80


def _check_access():
    if not request.env.user.has_group(GROUP):
        raise AccessError("Chỉ người có quyền Trợ lý quản trị mới dùng được trang này.")


def _ready():
    """Đã khai API key chưa — chưa thì trang báo ngay thay vì để tin chờ mãi."""
    return bool(request.env['hlv.admin.agent.config'].current().run_config()['api_key'])


def _personal_call(work):
    """Chạy một thao tác cá nhân hoá; lỗi nhập (UserError) trả về cho trang đọc thay vì văng lỗi."""
    try:
        work()
    except UserError as error:
        return {'ok': False, 'error': str(error)}
    return {'ok': True}


def _model_options():
    """Model cho ô chọn trên trang: ``[(mã, tên ngắn)]`` — bỏ phần giá trong ngoặc của nhãn Cấu hình."""
    return [(code, label.split(' (')[0]) for code, label in MODEL_CHOICES]


def _state(session, after_id=0):
    payload = session.client_state(after_id) if session else {'session_id': False, 'busy': False, 'messages': []}
    payload['ready'] = _ready()
    return payload


class AdminAgentChat(http.Controller):

    # website=True: module website sửa web.frontend_layout và cần biến 'website' / 'main_object' trong
    # context — thiếu là trang lỗi KeyError 'website'. sitemap=False: trang nội bộ, không đưa lên sitemap.
    @http.route(PAGE_URL, type='http', auth='user', methods=['GET'], website=True, sitemap=False)
    def page(self, **kw):
        if not request.env.user.has_group(GROUP):
            return request.not_found()
        return request.render('hlv_admin_agent.chat_page', {
            'user_name': request.env.user.name,
            'is_manager': request.env.user.has_group(MANAGER_GROUP),
            'models': _model_options(),
            'default_model': request.env['hlv.admin.agent.config'].current().model,
        })

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
    def send(self, session_id=0, text='', images=None, after_id=0, model=None, **kw):
        """Gửi một tin; chưa có cuộc (session_id rỗng) thì mở cuộc mới. Lỗi nhập trả trong 'error'."""
        _check_access()
        Session = request.env['hlv.admin.chat.session']
        created = not session_id
        session = Session.create({}) if created else Session.owned(session_id)
        if not session:
            return dict(_state(Session), error="Cuộc chat không còn.")
        try:
            # Model trước tin: post_user_message đánh thức runner, lượt này phải chạy model vừa chọn.
            session.set_model(model)
            session.post_user_message(text, images or [])
        except UserError as error:
            # Tin hỏng ở cuộc vừa mở: bỏ luôn cuộc rỗng, khỏi để rác ở cột trái. Kiểm tin chạy trước
            # mọi lệnh ghi nên cuộc chưa có tin nào.
            if created:
                session.sudo().unlink()
                session = Session
            return dict(_state(session, after_id), error=str(error))
        return _state(session, after_id)

    @http.route('/admin_agent/chat/model', type='json', auth='user', methods=['POST'])
    def model(self, session_id=0, model=None, **kw):
        """Đổi model của một cuộc (ô chọn model); lượt kế tiếp chạy model mới."""
        _check_access()
        session = request.env['hlv.admin.chat.session'].owned(session_id)
        return {'ok': bool(session) and session.set_model(model)}

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

    @http.route('/admin_agent/chat/stop', type='json', auth='user', methods=['POST'])
    def stop(self, session_id=0, **kw):
        """Nút dừng: trợ lý dừng ở bước kế (lệnh ghi đang chạy dở vẫn chạy xong)."""
        _check_access()
        session = request.env['hlv.admin.chat.session'].owned(session_id)
        return {'ok': bool(session) and session.request_stop()}

    # ── Cá nhân hoá: chỉ của chính người đang đăng nhập ──────────────────
    @http.route('/admin_agent/personal/get', type='json', auth='user', methods=['POST'])
    def personal_get(self, **kw):
        _check_access()
        user = request.env.user
        return {
            'instructions': request.env['hlv.admin.agent.profile'].instructions_for(user),
            'memories': request.env['hlv.admin.agent.memory'].for_user(user),
            'kinds': MEMORY_KINDS,
        }

    @http.route('/admin_agent/personal/instructions', type='json', auth='user', methods=['POST'])
    def personal_instructions(self, instructions='', **kw):
        _check_access()
        return _personal_call(lambda: request.env['hlv.admin.agent.profile'].save_for(
            request.env.user, instructions))

    @http.route('/admin_agent/personal/memory/add', type='json', auth='user', methods=['POST'])
    def memory_add(self, content='', kind='other', **kw):
        _check_access()
        return _personal_call(lambda: request.env['hlv.admin.agent.memory'].add_for_user(
            request.env.user, content, kind))

    @http.route('/admin_agent/personal/memory/update', type='json', auth='user', methods=['POST'])
    def memory_update(self, memory_id=0, content='', **kw):
        _check_access()
        memory = request.env['hlv.admin.agent.memory'].owned_by(request.env.user, memory_id)
        if not memory:
            return {'ok': False, 'error': "Không có ghi nhớ này."}
        return _personal_call(lambda: memory.set_content(content))

    @http.route('/admin_agent/personal/memory/delete', type='json', auth='user', methods=['POST'])
    def memory_delete(self, memory_id=0, **kw):
        _check_access()
        memory = request.env['hlv.admin.agent.memory'].owned_by(request.env.user, memory_id)
        if memory:
            memory.unlink()
        return {'ok': bool(memory)}
