# -*- coding: utf-8 -*-
"""Prompt của trợ lý, sửa trên Odoo.

Ba phần cố định (luật lõi, tài liệu A, tài liệu B) + các quy tắc riêng theo dòng hàng
ghép thành một system prompt. Agent so vân tay mỗi lần poll và tải lại khi đổi.

Claude ghi lại system prompt lúc MỞ phiên và giữ nguyên khi --resume, nên bản mới chỉ
vào các cuộc chat mới — trừ khi bấm "Áp dụng ngay" (xem action_apply_now).
"""
from odoo import _, api, fields, models
from odoo.tools import file_open

from ..services import build_system_prompt, prompt_version, render_special_rules

PARTS = [
    ('core', "Luật lõi"),
    ('naming', "Tài liệu A — Đặt tên và mã hàng"),
    ('category', "Tài liệu B — Phân nhóm hàng"),
]
DEFAULT_FILES = {
    'core': 'hlv_product_agent/data/prompt_defaults/system_prompt.md',
    'naming': 'hlv_product_agent/data/prompt_defaults/product_naming_rules.md',
    'category': 'hlv_product_agent/data/prompt_defaults/product_category_rules.md',
}


class HlvProductAgentPrompt(models.Model):
    _name = 'hlv.product.agent.prompt'
    _description = "Prompt trợ lý tạo mã hàng"
    _order = 'sequence, id'

    code = fields.Selection(PARTS, string="Phần", required=True, readonly=True)
    name = fields.Char("Tên", required=True)
    sequence = fields.Integer(default=10)
    content = fields.Text("Nội dung", required=True)
    revision_ids = fields.One2many('hlv.product.agent.prompt.revision', 'prompt_id', string="Lịch sử sửa")
    built_preview = fields.Text(
        "Prompt hoàn chỉnh gửi cho Claude", compute='_compute_built',
        help="Luật lõi + tài liệu A + quy tắc riêng theo dòng hàng + tài liệu B, đúng thứ tự Claude đọc.",
    )
    built_version = fields.Char("Phiên bản", compute='_compute_built')

    _sql_constraints = [
        ('code_uniq', 'unique(code)', "Mỗi phần prompt chỉ có một bản ghi."),
    ]

    # Không phụ thuộc field của riêng bản ghi: prompt hoàn chỉnh ghép từ MỌI phần và mọi
    # quy tắc riêng, đọc lại mỗi lần mở form.
    @api.depends('content')
    def _compute_built(self):
        text, version = self.build_prompt()
        for part in self:
            part.built_preview = text
            part.built_version = version

    @api.model
    def build_prompt(self):
        """System prompt hoàn chỉnh và vân tay của nó. Trả ``(text, version)``."""
        contents = {part.code: part.content for part in self.sudo().search([])}
        rules = self.env['hlv.product.naming.rule'].sudo().search([])
        text = build_system_prompt(
            contents.get('core'), contents.get('naming'), contents.get('category'),
            render_special_rules([rule.to_prompt_dict() for rule in rules]),
        )
        return text, prompt_version(text)

    # =========================================================================
    # Mặc định
    # =========================================================================
    @api.model
    def _default_content(self, code):
        with file_open(DEFAULT_FILES[code], 'r', encoding='utf-8') as handle:
            return handle.read().strip() + "\n"

    @api.model
    def _ensure_defaults(self):
        """Tạo phần nào còn thiếu từ file mặc định. Không đụng phần đã có (đã có thể bị sửa).

        Gọi từ data XML mỗi lần cài / nâng cấp module.
        """
        existing = set(self.sudo().search([]).mapped('code'))
        for sequence, (code, label) in enumerate(PARTS, start=1):
            if code not in existing:
                self.sudo().create({
                    'code': code, 'name': label, 'sequence': sequence * 10,
                    'content': self._default_content(code),
                })

    def action_reset_default(self):
        """Đưa phần này về bản mặc định đi kèm module (bản hiện tại vẫn còn trong lịch sử)."""
        for part in self:
            part.content = self._default_content(part.code)

    # =========================================================================
    # Lịch sử + áp dụng
    # =========================================================================
    def write(self, vals):
        if 'content' in vals:
            # Lưu bản CŨ trước khi ghi: sửa hỏng prompt là trợ lý hỏng cho mọi sale,
            # phải quay lại được ngay.
            changed = self.filtered(lambda part: (part.content or '') != (vals['content'] or ''))
            self.env['hlv.product.agent.prompt.revision'].sudo().create([
                {'prompt_id': part.id, 'content': part.content} for part in changed
            ])
        return super().write(vals)

    def action_apply_now(self):
        """Cho mọi cuộc chat đang mở dùng prompt mới từ lượt kế tiếp.

        Xoá mã phiên Claude: lượt sau agent mở phiên mới (prompt mới) và gửi kèm các tin
        gần nhất để Claude nắm lại ngữ cảnh. Cuộc đang xử lý dở vẫn xong bằng bản cũ.
        """
        sessions = self.env['hlv.product.chat.session'].sudo().search([
            ('closed', '=', False), ('state', '=', 'idle'), ('claude_session_id', '!=', False),
        ])
        sessions.write({'claude_session_id': False})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': _("%s cuộc chat đang mở sẽ dùng prompt mới từ tin kế tiếp.") % len(sessions),
            },
        }


class HlvProductAgentPromptRevision(models.Model):
    _name = 'hlv.product.agent.prompt.revision'
    _description = "Bản cũ của prompt trợ lý"
    _order = 'id desc'

    prompt_id = fields.Many2one('hlv.product.agent.prompt', required=True, ondelete='cascade', index=True)
    content = fields.Text("Nội dung", readonly=True)

    def action_restore(self):
        """Quay lại bản này. Bản đang dùng tự được lưu vào lịch sử (qua write)."""
        self.ensure_one()
        self.prompt_id.content = self.content
