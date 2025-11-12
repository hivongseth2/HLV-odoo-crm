import logging
import requests
import json
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

class AISalesConfig(models.Model):
    _name = 'hlv.ai.sales.config'
    _description = 'AI Sales Support Configuration'
    _rec_name = 'name'

    name = fields.Char('Configuration Name', default='AI Sales Config', required=True)
    active = fields.Boolean('Active', default=True)
    
    # ChatGPT Configuration
    openai_api_key = fields.Char('OpenAI API Key', required=True, help='Your OpenAI API key for ChatGPT')
    openai_model = fields.Selection([
        ('gpt-3.5-turbo', 'GPT-3.5 Turbo'),
        ('gpt-4', 'GPT-4'),
        ('gpt-4-turbo', 'GPT-4 Turbo'),
        ('gpt-4o', 'GPT-4o'),
    ], string='OpenAI Model', default='gpt-3.5-turbo', required=True)
    max_tokens = fields.Integer('Max Tokens', default=1000, help='Maximum tokens for AI response')
    temperature = fields.Float('Temperature', default=0.3, help='AI creativity level (0.0-1.0)')
    
    # AI Prompts
    product_analysis_prompt = fields.Text('Product Analysis Prompt', 
        default="""Bạn là một chuyên gia phân tích sản phẩm. Hãy phân tích thông tin sản phẩm được cung cấp và trả về kết quả dưới dạng JSON với các trường sau:
- product_code: mã sản phẩm (nếu có)
- product_name: tên sản phẩm được chuẩn hóa
- description: mô tả chi tiết sản phẩm
- category: danh mục sản phẩm
- keywords: từ khóa tìm kiếm (array)
- quantity: số lượng yêu cầu
- unit: đơn vị tính

Thông tin sản phẩm: {product_info}""",
        help='Prompt template for product analysis')
    
    supplier_inquiry_prompt = fields.Text('Supplier Inquiry Prompt',
        default="""Xin chào anh/chị,

Chúng tôi cần báo giá cho sản phẩm sau:
- Tên sản phẩm: {product_name}
- Mô tả: {description}
- Số lượng: {quantity} {unit}

Anh/chị vui lòng báo giá và thời gian giao hàng.

Cảm ơn anh/chị!""",
        help='Template for supplier inquiry message')
    
    # Response Configuration
    auto_send_quotation = fields.Boolean('Auto Send Quotation', default=True,
        help='Automatically send quotation to sales when ready')
    quotation_validity_days = fields.Integer('Quotation Validity (Days)', default=7,
        help='Number of days the quotation remains valid')
    
    # Inventory Configuration
    stock_buffer_percentage = fields.Float('Stock Buffer (%)', default=10.0,
        help='Buffer percentage for stock availability check')
    check_all_warehouses = fields.Boolean('Check All Warehouses', default=True,
        help='Check stock across all warehouses')
    
    @api.constrains('temperature')
    def _check_temperature(self):
        for record in self:
            if not (0.0 <= record.temperature <= 1.0):
                raise ValidationError(_('Temperature must be between 0.0 and 1.0'))
    
    @api.constrains('stock_buffer_percentage')
    def _check_stock_buffer(self):
        for record in self:
            if record.stock_buffer_percentage < 0:
                raise ValidationError(_('Stock buffer percentage cannot be negative'))
    
    def test_openai_connection(self):
        """Test OpenAI API connection"""
        self.ensure_one()
        try:
            try:
                # Try new OpenAI client (v1.0+)
                from openai import OpenAI
                client = OpenAI(api_key=self.openai_api_key)
                response = client.chat.completions.create(
                    model=self.openai_model,
                    messages=[{"role": "user", "content": "Hello, this is a test message."}],
                    max_tokens=10,
                    temperature=0.1
                )
            except ImportError:
                # Fallback to old OpenAI client
                import openai
                openai.api_key = self.openai_api_key
                response = openai.ChatCompletion.create(
                    model=self.openai_model,
                    messages=[{"role": "user", "content": "Hello, this is a test message."}],
                    max_tokens=10,
                    temperature=0.1
                )
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Success'),
                    'message': _('OpenAI API connection successful!'),
                    'type': 'success',
                }
            }
        except Exception as e:
            _logger.error("OpenAI API test failed: %s", str(e))
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': _('OpenAI API connection failed: %s') % str(e),
                    'type': 'danger',
                }
            }
    
    def analyze_product_with_ai(self, product_info):
        """Analyze product information using ChatGPT"""
        self.ensure_one()
        try:
            prompt = self.product_analysis_prompt.format(product_info=product_info)
            
            try:
                # Try new OpenAI client (v1.0+)
                from openai import OpenAI
                client = OpenAI(api_key=self.openai_api_key)
                response = client.chat.completions.create(
                    model=self.openai_model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=self.max_tokens,
                    temperature=self.temperature
                )
                ai_response = response.choices[0].message.content.strip()
            except ImportError:
                # Fallback to old OpenAI client
                import openai
                openai.api_key = self.openai_api_key
                response = openai.ChatCompletion.create(
                    model=self.openai_model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=self.max_tokens,
                    temperature=self.temperature
                )
                ai_response = response.choices[0].message.content.strip()
            
            _logger.info("AI Product Analysis Response: %s", ai_response)
            
            # Try to parse JSON response
            try:
                return json.loads(ai_response)
            except json.JSONDecodeError:
                # If not JSON, return as text
                return {"raw_response": ai_response}
                
        except Exception as e:
            _logger.error("AI product analysis failed: %s", str(e))
            raise UserError(_("AI analysis failed: %s") % str(e))
    
    @api.model
    def get_default_config(self):
        """Get the default active configuration"""
        config = self.search([('active', '=', True)], limit=1)
        if not config:
            raise UserError(_("No active AI Sales configuration found. Please configure the system first."))
        return config