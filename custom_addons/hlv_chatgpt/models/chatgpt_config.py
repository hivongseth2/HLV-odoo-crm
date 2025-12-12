# models/chatgpt_config.py
from odoo import models, fields, api

class HlvChatgptConfig(models.Model):
    _name = 'hlv.chatgpt.config'
    _description = 'Cấu hình OpenAI'
    
    name = fields.Char(default='Cấu hình OpenAI', required=True)
    active = fields.Boolean(default=True)
    
    # Thông số API
    api_key = fields.Char(string='OpenAI API Key', required=True, help="Bắt đầu bằng sk-...")
    
    # Thông số Prompt & Vector Store (Lấy từ code mẫu của bạn)
    prompt_id = fields.Char(string='Prompt ID', default='pmpt_69328af234508194a465ab3aad5c351f02f284d1c9c1b152')
    prompt_version = fields.Char(string='Version', default='3')
    vector_store_id = fields.Char(string='Vector Store ID', default='vs_69328ab5789081918759b56def1c641a')

    @api.model
    def get_config(self):
        return self.search([('active', '=', True)], limit=1)