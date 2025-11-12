
# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError

class WebsitePublicInventorySettings(models.TransientModel):
    _inherit = "res.config.settings"

    allowed_warehouse_ids = fields.Many2many(
        comodel_name="stock.warehouse",
        string="Public Warehouses",
        help="Warehouses whose stock will be shown on the public inventory page.",
    )
    
    # Chatbot AI Configuration
    chatbot_enabled = fields.Boolean(
        string="Enable AI Chatbot",
        help="Enable AI chatbot for product search and inventory assistance"
    )
    
    openai_api_key = fields.Char(
        string="OpenAI API Key",
        help="API key for ChatGPT integration"
    )
    
    openai_model = fields.Selection([
        ('gpt-3.5-turbo', 'GPT-3.5 Turbo'),
        ('gpt-4', 'GPT-4'),
        ('gpt-4-turbo', 'GPT-4 Turbo'),
    ], string="OpenAI Model", default='gpt-3.5-turbo')
    
    chatbot_max_tokens = fields.Integer(
        string="Max Tokens",
        default=500,
        help="Maximum tokens for AI responses"
    )
    
    chatbot_temperature = fields.Float(
        string="Temperature",
        default=0.3,
        help="AI response creativity (0.0-1.0)"
    )
    
    web_search_enabled = fields.Boolean(
        string="Enable Web Search",
        default=True,
        help="Enable web search when product not found in inventory"
    )

    @api.model
    def get_values(self):
        res = super().get_values()
        param = self.env["ir.config_parameter"].sudo()
        
        # Existing warehouse config
        raw = param.get_param("website_public_inventory_18.allowed_warehouse_ids", default="")
        ids = [int(x) for x in raw.split(",") if x.strip().isdigit()]
        res.update(allowed_warehouse_ids=[(6, 0, ids)])
        
        # Chatbot config
        res.update({
            'chatbot_enabled': param.get_param("website_public_inventory_18.chatbot_enabled", default=False),
            'openai_api_key': param.get_param("website_public_inventory_18.openai_api_key", default=""),
            'openai_model': param.get_param("website_public_inventory_18.openai_model", default="gpt-3.5-turbo"),
            'chatbot_max_tokens': int(param.get_param("website_public_inventory_18.chatbot_max_tokens", default=500)),
            'chatbot_temperature': float(param.get_param("website_public_inventory_18.chatbot_temperature", default=0.3)),
            'web_search_enabled': param.get_param("website_public_inventory_18.web_search_enabled", default=True),
        })
        
        return res

    def set_values(self):
        super().set_values()
        param = self.env["ir.config_parameter"].sudo()
        
        # Existing warehouse config
        ids = ",".join(str(x) for x in self.allowed_warehouse_ids.ids)
        param.set_param("website_public_inventory_18.allowed_warehouse_ids", ids)
        
        # Chatbot config
        param.set_param("website_public_inventory_18.chatbot_enabled", self.chatbot_enabled)
        param.set_param("website_public_inventory_18.openai_api_key", self.openai_api_key or "")
        param.set_param("website_public_inventory_18.openai_model", self.openai_model)
        param.set_param("website_public_inventory_18.chatbot_max_tokens", self.chatbot_max_tokens)
        param.set_param("website_public_inventory_18.chatbot_temperature", self.chatbot_temperature)
        param.set_param("website_public_inventory_18.web_search_enabled", self.web_search_enabled)
    
    def test_openai_connection(self):
        """Test OpenAI API connection"""
        if not self.openai_api_key:
            raise UserError("Please enter OpenAI API Key first")
        
        try:
            # Import here to avoid dependency issues if not installed
            import openai
            
            # Test with a simple completion
            client = openai.OpenAI(api_key=self.openai_api_key)
            response = client.chat.completions.create(
                model=self.openai_model,
                messages=[{"role": "user", "content": "Hello, this is a test."}],
                max_tokens=10
            )
            
            if response.choices:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Success!',
                        'message': 'OpenAI API connection successful',
                        'type': 'success',
                    }
                }
        except ImportError:
            raise UserError("OpenAI library not installed. Please install: pip install openai")
        except Exception as e:
            raise UserError(f"OpenAI API connection failed: {str(e)}")
