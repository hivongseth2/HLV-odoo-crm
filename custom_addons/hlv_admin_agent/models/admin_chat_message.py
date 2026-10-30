# -*- coding: utf-8 -*-
import base64
import json
import logging

from odoo import fields, models
from odoo.tools.image import image_process

from odoo.addons.hlv_product_agent.services import attachment_filename

_logger = logging.getLogger(__name__)

# Ảnh gửi thẳng cho Claude: thu về cạnh dài 1600px — ảnh điện thoại gốc vừa vượt giới hạn dung
# lượng của API vừa tốn token mà không đọc thêm được chữ nào.
API_IMAGE_MAX_SIDE = 1600
API_IMAGE_QUALITY = 85
API_IMAGE_TYPES = ('image/jpeg', 'image/png', 'image/gif', 'image/webp')


class HlvAdminChatMessage(models.Model):
    _name = 'hlv.admin.chat.message'
    _description = "Tin nhắn trợ lý quản trị"
    # Theo id: create_date chỉ chính xác tới giây, tin hỏi và tin trả lời cùng giây sẽ bị đảo.
    _order = 'id asc'

    session_id = fields.Many2one('hlv.admin.chat.session', required=True, ondelete='cascade', index=True)
    role = fields.Selection(
        [('user', "Người dùng"), ('assistant', "Trợ lý"), ('event', "Hệ thống")], required=True,
        help="Hệ thống: ghi chú Odoo tự chèn (đã tạo báo giá / cơ hội, lỗi). Không gửi cho Claude.",
    )
    content = fields.Text("Nội dung")
    attachment_ids = fields.Many2many('ir.attachment', string="Ảnh đính kèm")
    to_send = fields.Boolean("Chờ gửi cho Claude", default=False, index=True)
    claim_token = fields.Char(
        copy=False, index=True,
        help="Mã lượt đang cầm tin này. Tin tới lúc Claude đang chạy thì chưa có mã, đi ở lượt sau.",
    )
    # Lệnh cho trang (vd bảng so sánh thông số), JSON — trang chỉ vẽ, không chạy gì.
    client_action = fields.Char(copy=False)
    # Câu trả lời: các bước trợ lý đã làm trong lượt (JSON list chữ), trang hiện thu gọn "Đã làm N bước".
    steps = fields.Text(copy=False)

    def to_client_dict(self):
        """Dữ liệu một tin cho trang chat."""
        self.ensure_one()
        return {
            'id': self.id,
            'role': self.role,
            'content': self.content or '',
            'image_ids': self.attachment_ids.ids,
            'date': fields.Datetime.to_string(self.create_date),
            'action': json.loads(self.client_action) if self.client_action else None,
            'steps': json.loads(self.steps) if self.steps else [],
        }

    def to_prompt_dict(self):
        """Dữ liệu một tin cho build_turn_prompt của trợ lý tạo mã."""
        self.ensure_one()
        return {
            'role': self.role,
            'text': self.content or '',
            'attachments': [attachment_filename(att.id, att.name) for att in self.attachment_ids],
        }

    def api_image_payloads(self):
        """Ảnh của tin để gửi Claude API: list ``{'filename', 'mimetype', 'data'}`` (data base64).

        Ảnh không thu nhỏ được thì gửi bản gốc nếu API nhận định dạng đó; định dạng lạ thì bỏ
        (Claude vẫn thấy tên file).
        """
        self.ensure_one()
        payloads = []
        for att in self.attachment_ids:
            raw, mimetype = att.raw or b'', (att.mimetype or '').lower()
            try:
                raw = image_process(raw, size=(API_IMAGE_MAX_SIDE, API_IMAGE_MAX_SIDE),
                                    quality=API_IMAGE_QUALITY, output_format='JPEG')
                mimetype = 'image/jpeg'
            except Exception:  # noqa: BLE001 — ảnh hỏng không được làm chết cả lượt
                _logger.warning("ADMIN_AGENT không thu nhỏ được ảnh %s", att.id, exc_info=True)
            if raw and mimetype in API_IMAGE_TYPES:
                payloads.append({'filename': attachment_filename(att.id, att.name), 'mimetype': mimetype,
                                 'data': base64.b64encode(raw).decode('ascii')})
        return payloads
