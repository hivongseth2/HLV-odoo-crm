# -*- coding: utf-8 -*-
from odoo import models, fields, api

class HlvChatgptConfig(models.Model):
    _name = 'hlv.chatgpt.config'
    _description = 'Cấu hình Multi-Agent'

    name = fields.Char(string='Tên cấu hình', default='Cấu hình Chính')
    api_key = fields.Char(string='OpenAI API Key', required=True)
    
    # --- 3 CON AGENT ---
    router_id = fields.Char(string='Router ID (Tổng đài)', required=True, help="ID asst_...")
    stock_id = fields.Char(string='Stock ID (Kho)', required=True, help="ID asst_...")
    naming_id = fields.Char(string='Naming ID (Đặt tên)', required=True, help="ID asst_...")

    @api.model
    def get_config(self):
        return self.search([], limit=1)