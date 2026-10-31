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
    ('assist', "Tra cứu & tương tác"),
]
# Vân tay (prompt_version) các bản mặc định đã phát hành trước. Phần trong DB còn đúng một bản
# này = chưa ai sửa, nâng cấp module thì thay bằng bản mặc định hiện tại.
OLD_DEFAULT_VERSIONS = {
    'assist': {
        '2c0a2969651238a1',  # 18.0.1.4.0: còn hướng dẫn vẽ bảng show_panel
        'a8e4693930aa1257',  # 18.0.1.5.0: tim_ncc_dong_hang chỉ theo từ khoá
        'e35043ee76354515',  # 18.0.1.6.0: chưa có định dạng chữ / ảnh, chưa dặn chủ động tìm web
        '35043f5c0fb79a58',  # 18.0.1.7.0: trả lời dài, chưa có nút lựa chọn [[...]]
        '79f0f9e068dff22a',  # 18.0.1.8.0: bộ lựa chọn mẫu cố định, Claude chép y nguyên
        '225ec1aa51313458',  # 18.0.1.9.0: chưa hỏi bằng ảnh khi tạo mã mà chưa rõ hàng
        '2dfe5b129870f24b',  # 18.0.1.10.0: hỏi chung loại hàng bị hiểu là yêu cầu tạo, chưa tư vấn
        'a4d95385c0dcbe20',  # 18.0.1.11.0: hết hàng chưa tự đề xuất mã thay thế, chưa có so sánh
        '7cb07556865a2f5c',  # 18.0.1.12.0: tìm web chưa ưu tiên trang Việt Nam, chưa gợi ý giá mua
        'e695c20e95f58db3',  # 18.0.1.13.0: tạo mã mơ hồ chưa dặn tìm trước, "ai giữ" bỏ phiếu chuyển kho
        '465717d24c8a2bee',  # 18.0.1.14.0: tư vấn chưa dò các cách gọi khác của cùng loại máy
        '4d327e8098f509ef',  # 18.0.1.15.0: hết lượt tìm web thì tưởng bị chặn luôn ở các lượt sau
        '5533442db2fe2ad4',  # 18.0.1.16.1: hãng hết hàng chưa đưa hãng khác, mời tạo mã chưa tra MISA
        '352e8f35ecb3123c',  # 18.0.1.16.2: hỏi lại thông tin sale đã ghi, hỏi hãng vật tư chung, chưa hỏi bằng nút
        '339b1144b28f5e4d',  # 18.0.1.17.0: hãng hết hàng vẫn đẩy thành nút thay vì liệt kê hãng khác
        'cb597b11c62a5772',  # 18.0.1.17.1: mã hàng chưa bấm được, tìm ra mã chưa kèm giá
        '7d49477661273757',  # 18.0.1.18.2: tìm mã thay thế trả lời "chưa chắc" thay vì tìm web thông số
        '82559cb54d487b10',  # 18.0.1.18.3: vẫn "chưa tra thông số mã X", gộp nhiều model một câu tìm
        '839af6e80c195eeb',  # 18.0.1.18.4: ghép Packout chưa quét hết hệ, lắp lẫn pin không tìm web, còn "chưa kiểm chứng"
        '8f562ddea6c79e0b',  # 18.0.1.18.5: còn câu rào cuối bài "em chưa đối chiếu được..."
        '82ce4c87ee7c55f5',  # 18.0.1.18.6: hàng trên phiếu chuyển nội bộ coi là hết, chào mã thay thế
        '1ed90ae549168f34',  # 18.0.1.18.7: chưa báo trễ hạn, gọi hàng đang chuyển là khách giữ
        '22839bd0d3fc775a',  # 18.0.1.18.9: mã tương đương chưa có nút hỏi nhu cầu khách
        '518d0d48337dc3c3',  # 18.0.1.19.0: chưa dùng thông số đã lưu, lần nào cũng tìm web
        '108612360652972f',  # 18.0.1.20.0: tìm web xong không gọi luu_thong_so
        '3f6180851ef6365c',  # 18.0.1.20.3: 10x10x100 so với mã có sẵn 10 x 100 báo "không trùng rõ ràng"
        '35217551aa40301c',  # 18.0.1.20.5: "kìm cắt" trống hiểu là tạo mã, báo số mẫu gồm cả phụ tùng
        'bef7976d2bf8da98',  # 18.0.1.20.7: tìm "tất cả" theo tim_hang_tuong_tu (xếp hạng + cắt), sót mã bán chậm
    },
}
DEFAULT_FILES = {
    'core': 'hlv_product_agent/data/prompt_defaults/system_prompt.md',
    'naming': 'hlv_product_agent/data/prompt_defaults/product_naming_rules.md',
    'category': 'hlv_product_agent/data/prompt_defaults/product_category_rules.md',
    'assist': 'hlv_product_agent/data/prompt_defaults/assistant_tools.md',
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
            contents.get('assist'),
        )
        return text, prompt_version(text)

    # =========================================================================
    # Mặc định
    # =========================================================================
    @api.model
    def _default_content(self, code):
        # file_open của Odoo không nhận encoding: đọc byte rồi tự giải mã UTF-8, không
        # phó mặc cho bảng mã mặc định của server (tài liệu toàn tiếng Việt có dấu).
        with file_open(DEFAULT_FILES[code], 'rb') as handle:
            return handle.read().decode('utf-8').strip() + "\n"

    @api.model
    def _ensure_defaults(self):
        """Tạo phần nào còn thiếu từ file mặc định; phần còn nguyên bản mặc định CŨ thì lên bản mới.

        Phần đã bị sửa tay (vân tay khác mọi bản mặc định cũ) thì không đụng. Gọi từ data XML
        mỗi lần cài / nâng cấp module.
        """
        parts = {part.code: part for part in self.sudo().search([])}
        for sequence, (code, label) in enumerate(PARTS, start=1):
            part = parts.get(code)
            if not part:
                self.sudo().create({
                    'code': code, 'name': label, 'sequence': sequence * 10,
                    'content': self._default_content(code),
                })
            elif prompt_version((part.content or '').strip() + "\n") in OLD_DEFAULT_VERSIONS.get(code, ()):
                # Ghi qua write(): bản cũ vẫn vào lịch sử, quay lại được.
                part.content = self._default_content(code)

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
