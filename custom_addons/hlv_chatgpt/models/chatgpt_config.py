from odoo import models, fields, api

class HlvChatgptConfig(models.Model):
    _name = 'hlv.chatgpt.config'
    _description = 'Cấu hình OpenAI'
    _rec_name = 'name'

    name = fields.Char(default='Cấu hình OpenAI', required=True)
    active = fields.Boolean(default=True)
    
    # API Key
    api_key = fields.Char(string='OpenAI API Key', required=True, password=True, help="Bắt đầu bằng sk-...")
    
    # 3 Prompt ID (Có default như bạn yêu cầu)
    router_prompt_id = fields.Char(
        string='Router Prompt ID', 
        default='pmpt_693bb54cde948195b2faa0835d48232c04addb4234a38bd2',
        required=True, 
        help="ID Prompt phân luồng (pmpt_...)"
    )
    
    stock_prompt_id = fields.Char(
        string='Stock Agent Prompt ID', 
        default='pmpt_693bb17638e08193b5b9cae2301b21ac01fefd44d072ae79',
        required=True, 
        help="ID Prompt tra cứu kho (pmpt_...)"
    )
    
    naming_prompt_id = fields.Char(
        string='Naming Agent Prompt ID', 
        default='pmpt_69328af234508194a465ab3aad5c351f02f284d1c9c1b152',
        required=True, 
        help="ID Prompt đặt tên (pmpt_...)"
    )
    product_vector_store_id = fields.Char(
        string='Vector Store ID (Kho)',
        help="ID của Vector Store chứa file danh sách sản phẩm (vs_...)",
        default="" 
    )

    @api.model
    def get_config(self):
        return self.search([('active', '=', True)], limit=1)