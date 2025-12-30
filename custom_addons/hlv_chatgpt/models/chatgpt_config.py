# -*- coding: utf-8 -*-
from odoo import models, fields, api

class HlvChatgptConfig(models.Model):
    _name = 'hlv.chatgpt.config'
    _description = 'Cấu hình Single Agent'
    
    active = fields.Boolean(default=True)
    name = fields.Char(string='Tên cấu hình', default='Cấu hình Chính')
    api_key = fields.Char(string='OpenAI API Key', required=True)
    
    # Chỉ giữ 1 con duy nhất
    product_manager_id = fields.Char(
        string='Product Manager ID', 
        required=True, 
        help="ID của Assistant (đã cấu hình File Search và Function Calling trên OpenAI)"
    )

    @api.model
    def get_config(self):
        return self.search([('active', '=', True)], limit=1)