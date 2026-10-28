# -*- coding: utf-8 -*-
import base64
import json
import logging

from odoo import fields, models
from odoo.tools.image import image_process

from ..services import attachment_filename

_logger = logging.getLogger(__name__)

# Chế độ API gửi ảnh thẳng cho Claude: thu về cạnh dài 1600px. Ảnh điện thoại gốc vừa
# vượt giới hạn dung lượng của API vừa tốn token mà không đọc thêm được chữ nào.
API_IMAGE_MAX_SIDE = 1600
API_IMAGE_QUALITY = 85
API_IMAGE_TYPES = ('image/jpeg', 'image/png', 'image/gif', 'image/webp')


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
    # Lệnh cho trang đang mở (vd mở tra tồn đúng mã), JSON. Khung chat chỉ chạy với tin
    # MỚI tới, không chạy lại khi tải lại trang — xem product_chat.js.
    client_action = fields.Char(copy=False)
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
            'action': json.loads(self.client_action) if self.client_action else None,
        }

    def to_prompt_dict(self):
        """Dữ liệu một tin cho build_turn_prompt."""
        self.ensure_one()
        return {
            'role': self.role,
            'text': self.content or '',
            'attachments': [attachment_filename(att.id, att.name) for att in self.attachment_ids],
        }

    def api_image_payloads(self):
        """Ảnh của tin này để gửi Claude API: list ``{'filename', 'mimetype', 'data'}``.

        data là base64 (str) của ảnh đã thu nhỏ về JPEG. Ảnh không thu nhỏ được thì gửi bản
        gốc nếu là định dạng API nhận; định dạng lạ thì bỏ (Claude vẫn thấy tên file).
        """
        self.ensure_one()
        payloads = []
        for att in self.attachment_ids:
            filename = attachment_filename(att.id, att.name)
            raw, mimetype = att.raw or b'', (att.mimetype or '').lower()
            try:
                raw = image_process(raw, size=(API_IMAGE_MAX_SIDE, API_IMAGE_MAX_SIDE),
                                    quality=API_IMAGE_QUALITY, output_format='JPEG')
                mimetype = 'image/jpeg'
            except Exception:  # noqa: BLE001 — ảnh hỏng không được làm chết cả lượt
                _logger.warning("PRODUCT_AGENT không thu nhỏ được ảnh %s", att.id, exc_info=True)
            if raw and mimetype in API_IMAGE_TYPES:
                payloads.append({'filename': filename, 'mimetype': mimetype,
                                 'data': base64.b64encode(raw).decode('ascii')})
        return payloads
