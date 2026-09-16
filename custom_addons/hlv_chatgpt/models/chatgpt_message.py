# -*- coding: utf-8 -*-
import base64
import logging

import requests

from odoo import models, fields

from ..services import apply_permission_marker, strip_permission_markers

_logger = logging.getLogger(__name__)

IMAGE_DOWNLOAD_TIMEOUT = 15
# OpenAI từ chối ảnh quá lớn; chặn sớm ở đây để khỏi tốn băng thông và token.
MAX_IMAGE_BYTES = 8 * 1024 * 1024

IMAGE_ONLY_PROMPT = "Hãy phân tích hình ảnh này."
IMAGE_LOST_NOTE = "[Người dùng có gửi kèm 1 ảnh]"


class HlvChatgptMessage(models.Model):
    _name = 'hlv.chatgpt.message'
    _description = 'Lịch sử tin nhắn Chat AI'
    # Sắp theo id chứ không theo create_date: create_date chỉ chính xác tới giây nên
    # tin của user và tin trả lời trong cùng một giây có thể bị đảo thứ tự.
    _order = 'id asc'

    session_id = fields.Many2one('hlv.chatgpt.session', ondelete='cascade', index=True, required=True)
    role = fields.Selection(
        [('user', 'User'), ('assistant', 'AI'), ('system', 'System')],
        required=True,
    )
    content = fields.Text(string="Nội dung")
    image_url = fields.Char(string="Ảnh đính kèm")
    zalo_msg_id = fields.Char(string="Msg ID Zalo")
    to_send = fields.Boolean(
        string="Chờ gửi cho AI",
        default=False,
        index=True,
        help="Tin của người dùng chưa được đưa vào ngữ cảnh OpenAI. "
             "Lượt gọi kế tiếp sẽ gửi kèm rồi tắt cờ này.",
    )

    _sql_constraints = [
        # Chốt chống trùng ở mức DB: hai webhook Zalo retry chạy song song đều qua được
        # bước search_count, chỉ unique index mới chặn được.
        ('zalo_msg_id_uniq', 'unique(zalo_msg_id)', 'Tin nhắn Zalo này đã được ghi nhận.'),
    ]

    def to_openai_input(self, with_image=True, is_admin=False):
        """Chuyển message thành một input item của Responses API.

        Nhận: cờ with_image (False thì không tải ảnh, chỉ ghi chú là có ảnh) và cờ
        is_admin để gắn marker quyền vào tin của người dùng.
        Trả: dict ``{'role': ..., 'content': ...}``.
        Biên: message rỗng hoàn toàn -> chỉ còn marker quyền, đủ để API không lỗi.
        """
        self.ensure_one()
        if self.role != 'user':
            return {'role': self.role, 'content': (self.content or "").strip() or "..."}

        data_uri = self._image_data_uri() if (self.image_url and with_image) else None
        raw_text = self.content
        # Người dùng chỉ gửi ảnh: cần một câu mồi, nếu không model không biết làm gì.
        # Xét trên nội dung đã bóc marker để người dùng không lách bằng cách gõ marker giả.
        if data_uri and not strip_permission_markers(raw_text):
            raw_text = IMAGE_ONLY_PROMPT

        content = [{'type': 'input_text', 'text': apply_permission_marker(raw_text, is_admin)}]
        if data_uri:
            content.append({'type': 'input_image', 'image_url': data_uri})
        elif self.image_url:
            content.append({'type': 'input_text', 'text': IMAGE_LOST_NOTE})
        return {'role': 'user', 'content': content}

    def _image_data_uri(self):
        """Tải ảnh về và bọc thành data URI. Trả None nếu tải hỏng hoặc ảnh quá lớn."""
        self.ensure_one()
        try:
            response = requests.get(self.image_url, timeout=IMAGE_DOWNLOAD_TIMEOUT)
            response.raise_for_status()
        except Exception as error:
            _logger.warning("Không tải được ảnh %s: %s", self.image_url, error)
            return None

        if len(response.content) > MAX_IMAGE_BYTES:
            _logger.warning("Bỏ qua ảnh %s: %s bytes vượt giới hạn", self.image_url, len(response.content))
            return None

        # Lấy mime thật từ header thay vì mặc định jpeg: ảnh Zalo có thể là png/webp.
        mime = (response.headers.get('Content-Type') or '').split(';')[0].strip()
        if not mime.startswith('image/'):
            mime = 'image/jpeg'
        return "data:%s;base64,%s" % (mime, base64.b64encode(response.content).decode('ascii'))
