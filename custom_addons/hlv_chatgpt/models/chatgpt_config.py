# -*- coding: utf-8 -*-
from odoo import models, fields, api

from ..services import DEFAULT_VECTOR_STORE_IDS, parse_vector_store_ids


class HlvChatgptConfig(models.Model):
    _name = 'hlv.chatgpt.config'
    _description = 'Cấu hình Chat AI'

    active = fields.Boolean(default=True)
    name = fields.Char(string='Tên cấu hình', default='Cấu hình Chính')
    api_key = fields.Char(string='OpenAI API Key', required=True)
    prompt_id = fields.Char(
        string='Prompt ID',
        required=True,
        help="ID của Stored Prompt trên OpenAI (VD: pmpt_...). "
             "Toàn bộ chỉ dẫn nghiệp vụ nằm trong prompt này.",
    )
    vector_store_ids = fields.Char(
        string='Vector Store IDs',
        default=','.join(DEFAULT_VECTOR_STORE_IDS),
        help="Danh sách vector store cho file_search, ngăn bởi dấu phẩy. "
             "Để trống nếu không dùng file_search.",
    )
    enable_web_search = fields.Boolean(
        string='Bật Web Search',
        default=True,
        help="Cho phép AI tra cứu web khi không tìm thấy thông tin trong file và MISA.",
    )

    @api.model
    def get_config(self):
        """Lấy cấu hình đang hoạt động. Trả recordset rỗng nếu chưa cấu hình."""
        return self.search([('active', '=', True)], limit=1)

    def get_vector_store_ids(self):
        """Trả list[str] vector store id đã tách từ cấu hình. Rỗng nếu không cấu hình."""
        self.ensure_one()
        return parse_vector_store_ids(self.vector_store_ids)
