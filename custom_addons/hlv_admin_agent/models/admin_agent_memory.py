# -*- coding: utf-8 -*-
"""Ghi nhớ lâu dài và hướng dẫn riêng của từng người dùng trợ lý quản trị (như memory của Claude).

Mỗi người chỉ thấy / sửa của mình (trên trang chat và qua tool); nhóm Quản lý xem được của mọi người
ở backend. Mỗi lượt, khối "về người dùng" (personal_block) được nạp sau system prompt chung.
"""
from odoo import api, fields, models
from odoo.exceptions import UserError

from ..services.personal import MEMORY_KINDS, MEMORY_MAX_CHARS, personal_block

# Prompt nạp mỗi lượt: chặn danh sách phình vô hạn (mỗi ghi nhớ tốn token ở mọi lượt về sau).
MAX_MEMORIES_PER_USER = 100
INSTRUCTIONS_MAX_CHARS = 4000


class HlvAdminAgentMemory(models.Model):
    _name = 'hlv.admin.agent.memory'
    _description = "Ghi nhớ của trợ lý quản trị"
    _order = 'user_id, kind, id'
    _rec_name = 'content'

    user_id = fields.Many2one('res.users', string="Người dùng", required=True, index=True,
                              default=lambda self: self.env.user, ondelete='cascade')
    kind = fields.Selection(MEMORY_KINDS, string="Loại", required=True, default='other')
    content = fields.Char("Nội dung", required=True, size=MEMORY_MAX_CHARS)
    session_id = fields.Many2one('hlv.admin.chat.session', string="Ghi trong cuộc chat", ondelete='set null',
                                 help="Trống = người dùng tự thêm trên trang.")

    @api.model
    def for_user(self, user):
        """Ghi nhớ của một người: list ``{'id', 'kind', 'content'}``."""
        memories = self.sudo().search([('user_id', '=', user.id)])
        return [{'id': mem.id, 'kind': mem.kind, 'content': mem.content} for mem in memories]

    @api.model
    def add_for_user(self, user, content, kind='other', session=None):
        """Thêm một ghi nhớ. Raise UserError khi rỗng / quá dài / quá số lượng / loại lạ."""
        content = ' '.join((content or '').split())
        if not content:
            raise UserError("Ghi nhớ rỗng.")
        if len(content) > MEMORY_MAX_CHARS:
            raise UserError("Ghi nhớ quá %s ký tự — viết ngắn lại." % MEMORY_MAX_CHARS)
        if kind not in dict(MEMORY_KINDS):
            raise UserError("Loại ghi nhớ không hợp lệ: %s." % kind)
        if self.sudo().search_count([('user_id', '=', user.id)]) >= MAX_MEMORIES_PER_USER:
            raise UserError("Đã đủ %s ghi nhớ — xoá bớt cái cũ trước." % MAX_MEMORIES_PER_USER)
        return self.sudo().create({'user_id': user.id, 'content': content, 'kind': kind,
                                   'session_id': session.id if session else False})

    @api.model
    def owned_by(self, user, memory_id):
        """Ghi nhớ memory_id nếu thuộc ``user``; rỗng nếu không (id sai / của người khác)."""
        try:
            memory_id = int(memory_id or 0)
        except (TypeError, ValueError):
            return self.browse()
        return self.sudo().search([('id', '=', memory_id), ('user_id', '=', user.id)], limit=1)

    def set_content(self, content):
        self.ensure_one()
        content = ' '.join((content or '').split())
        if not content or len(content) > MEMORY_MAX_CHARS:
            raise UserError("Ghi nhớ phải có nội dung, tối đa %s ký tự." % MEMORY_MAX_CHARS)
        self.sudo().content = content


class HlvAdminAgentProfile(models.Model):
    _name = 'hlv.admin.agent.profile'
    _description = "Hướng dẫn riêng cho trợ lý quản trị"
    _rec_name = 'user_id'

    user_id = fields.Many2one('res.users', string="Người dùng", required=True, index=True, ondelete='cascade')
    instructions = fields.Text("Hướng dẫn riêng", help="Người dùng tự viết: trợ lý theo ở mọi cuộc chat.")

    _sql_constraints = [('user_uniq', 'unique(user_id)', "Mỗi người dùng chỉ có một hướng dẫn riêng.")]

    @api.model
    def instructions_for(self, user):
        return self.sudo().search([('user_id', '=', user.id)], limit=1).instructions or ''

    @api.model
    def save_for(self, user, instructions):
        """Lưu hướng dẫn riêng của ``user`` (tạo nếu chưa có). Raise UserError khi quá dài."""
        instructions = (instructions or '').strip()
        if len(instructions) > INSTRUCTIONS_MAX_CHARS:
            raise UserError("Hướng dẫn riêng tối đa %s ký tự." % INSTRUCTIONS_MAX_CHARS)
        profile = self.sudo().search([('user_id', '=', user.id)], limit=1)
        if profile:
            profile.instructions = instructions
        else:
            self.sudo().create({'user_id': user.id, 'instructions': instructions})

    @api.model
    def block_for(self, user):
        """Khối "về người dùng" cho system prompt: hướng dẫn riêng + ghi nhớ của ``user``."""
        return personal_block(user.name, self.instructions_for(user),
                              self.env['hlv.admin.agent.memory'].for_user(user))
