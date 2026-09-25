# -*- coding: utf-8 -*-
from odoo import fields, models

from ..services import attachment_filename


class HlvProductChatMessage(models.Model):
    _name = 'hlv.product.chat.message'
    _description = "Tin nhắn trợ lý tạo mã hàng"
    # Theo id chứ không theo create_date: create_date chỉ chính xác tới giây nên tin
    # của sale và tin trả lời trong cùng một giây có thể bị đảo thứ tự.
    _order = 'id asc'

    session_id = fields.Many2one(
        'hlv.product.chat.session', required=True, ondelete='cascade', index=True,
    )
    role = fields.Selection(
        [('user', "Nhân viên"), ('assistant', "Trợ lý"), ('event', "Hệ thống")],
        required=True,
        help="Hệ thống: ghi chú do Odoo tự chèn (đã tạo/sửa trên MISA, lỗi máy xử lý). "
             "Không gửi cho Claude.",
    )
    content = fields.Text("Nội dung")
    attachment_ids = fields.Many2many('ir.attachment', string="Ảnh đính kèm")
    to_send = fields.Boolean(
        "Chờ gửi cho Claude", default=False, index=True,
        help="Tin của sale chưa được đưa vào ngữ cảnh Claude.",
    )
    claim_token = fields.Char(
        copy=False, index=True,
        help="Mã lượt xử lý đang cầm tin này. Tin tới trong lúc Claude đang chạy thì chưa "
             "có mã, sẽ đi ở lượt kế tiếp thay vì bị đánh dấu xong oan.",
    )

    def to_client_dict(self):
        """Dữ liệu một tin cho khung chat trên trình duyệt."""
        self.ensure_one()
        return {
            'id': self.id,
            'role': self.role,
            'content': self.content or '',
            'image_ids': self.attachment_ids.ids,
            'date': fields.Datetime.to_string(self.create_date),
        }

    def to_prompt_dict(self):
        """Dữ liệu một tin cho build_turn_prompt."""
        self.ensure_one()
        return {
            'role': self.role,
            'text': self.content or '',
            'attachments': [attachment_filename(att.id, att.name) for att in self.attachment_ids],
        }
