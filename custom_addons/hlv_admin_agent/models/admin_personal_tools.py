# -*- coding: utf-8 -*-
"""Chạy tool ghi nhớ / tìm cuộc chat cũ của trợ lý quản trị.

Mọi tool chỉ đụng dữ liệu của đúng người đang chat (session.user_id) — kể cả khi người đó là quản lý:
quản lý xem của người khác ở backend, không qua trợ lý. Kết quả luôn có 'status'.
"""
from odoo import fields, models
from odoo.exceptions import UserError

from ..services.personal import snippet

SEARCH_SESSIONS = 8
SNIPPETS_PER_SESSION = 2
READ_MESSAGES = 40
READ_MESSAGE_CHARS = 1500


class HlvAdminPersonalTools(models.AbstractModel):
    _name = 'hlv.admin.personal.tools'
    _description = "Tool ghi nhớ / cuộc chat cũ của trợ lý quản trị"

    def run(self, session, name, args):
        handler = {
            'ghi_nho': self._remember,
            'sua_ghi_nho': self._edit_memory,
            'quen': self._forget,
            'tim_cuoc_chat_cu': self._search_chats,
            'doc_cuoc_chat_cu': self._read_chat,
        }.get(name)
        if not handler:
            return {'status': 'error', 'message': "Tool %s chưa được hỗ trợ." % name}
        if not isinstance(args, dict):
            return {'status': 'error', 'message': "Tham số phải là object JSON."}
        try:
            return handler(session, args)
        except UserError as error:
            return {'status': 'error', 'message': str(error)}

    # ---- Ghi nhớ: mỗi thay đổi để lại ghi chú trong cuộc chat, người dùng thấy em đã nhớ / quên gì.
    def _remember(self, session, args):
        memory = self.env['hlv.admin.agent.memory'].add_for_user(
            session.user_id, args.get('noi_dung'), args.get('loai') or 'other', session)
        session.post_event("Đã ghi nhớ #%s: %s" % (memory.id, memory.content))
        return {'status': 'success', 'id': memory.id, 'message': "Đã ghi nhớ."}

    def _edit_memory(self, session, args):
        memory = self.env['hlv.admin.agent.memory'].owned_by(session.user_id, args.get('id'))
        if not memory:
            return {'status': 'not_found', 'message': "Không có ghi nhớ #%s của người dùng này." % args.get('id')}
        old = memory.content
        memory.set_content(args.get('noi_dung'))
        session.post_event("Đã sửa ghi nhớ #%s: «%s» → «%s»" % (memory.id, old, memory.content))
        return {'status': 'success', 'message': "Đã sửa ghi nhớ."}

    def _forget(self, session, args):
        memory = self.env['hlv.admin.agent.memory'].owned_by(session.user_id, args.get('id'))
        if not memory:
            return {'status': 'not_found', 'message': "Không có ghi nhớ #%s của người dùng này." % args.get('id')}
        session.post_event("Đã quên ghi nhớ #%s: %s" % (memory.id, memory.content))
        memory.unlink()
        return {'status': 'success', 'message': "Đã xoá ghi nhớ."}

    # ---- Cuộc chat cũ
    def _search_chats(self, session, args):
        keyword = ' '.join((args.get('tu_khoa') or '').split())
        if len(keyword) < 2:
            return {'status': 'error', 'message': "Từ khoá quá ngắn."}
        messages = self.env['hlv.admin.chat.message'].sudo().search([
            ('session_id.user_id', '=', session.user_id.id), ('session_id', '!=', session.id),
            ('content', 'ilike', keyword),
        ], order='id desc', limit=SEARCH_SESSIONS * 5)
        found = {}
        for message in messages:
            hits = found.setdefault(message.session_id, [])
            if len(found) > SEARCH_SESSIONS:
                found.pop(message.session_id)
                break
            if len(hits) < SNIPPETS_PER_SESSION:
                hits.append({'role': message.role, 'date': fields.Datetime.to_string(message.create_date),
                             'text': snippet(message.content, keyword)})
        if not found:
            return {'status': 'not_found', 'message': "Không cuộc chat cũ nào có '%s'." % keyword}
        return {'status': 'found', 'cuoc_chat': [
            {'session_id': chat.id, 'ten': chat.name,
             'hoat_dong_cuoi': fields.Datetime.to_string(chat.last_activity), 'doan_khop': hits}
            for chat, hits in found.items()
        ]}

    def _read_chat(self, session, args):
        try:
            chat_id = int(args.get('session_id') or 0)
        except (TypeError, ValueError):
            chat_id = 0
        chat = self.env['hlv.admin.chat.session'].sudo().search(
            [('id', '=', chat_id), ('user_id', '=', session.user_id.id)], limit=1)
        if not chat:
            return {'status': 'not_found', 'message': "Không có cuộc chat #%s của người dùng này." % chat_id}
        messages = chat.message_ids.filtered('content')[-READ_MESSAGES:]
        return {'status': 'found', 'ten': chat.name, 'tom_tat_phan_dau': chat.summary or '',
                'tin': [{'role': msg.role, 'date': fields.Datetime.to_string(msg.create_date),
                         'text': msg.content[:READ_MESSAGE_CHARS]} for msg in messages]}
