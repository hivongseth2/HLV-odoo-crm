# -*- coding: utf-8 -*-

from odoo import models, fields, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # AI Sales Support Settings
    ai_sales_enabled = fields.Boolean(
        string='Enable AI Sales Support',
        config_parameter='ai_sales_support.enabled',
        help='Enable AI-powered sales support functionality'
    )
    
    # ChatGPT Configuration
    chatgpt_api_key = fields.Char(
        string='ChatGPT API Key',
        config_parameter='ai_sales_support.chatgpt_api_key',
        help='OpenAI API key for ChatGPT integration'
    )
    chatgpt_model = fields.Selection([
        ('gpt-3.5-turbo', 'GPT-3.5 Turbo'),
        ('gpt-4', 'GPT-4'),
        ('gpt-4-turbo', 'GPT-4 Turbo'),
        ('gpt-4o', 'GPT-4o'),
    ], string='ChatGPT Model', 
       default='gpt-3.5-turbo',
       config_parameter='ai_sales_support.chatgpt_model',
       help='ChatGPT model to use for AI processing')
    
    chatgpt_max_tokens = fields.Integer(
        string='Max Tokens',
        default=1000,
        config_parameter='ai_sales_support.chatgpt_max_tokens',
        help='Maximum number of tokens for ChatGPT response'
    )
    
    chatgpt_temperature = fields.Float(
        string='Temperature',
        default=0.7,
        config_parameter='ai_sales_support.chatgpt_temperature',
        help='Temperature for ChatGPT response (0.0 to 1.0)'
    )
    
    # Zalo Configuration
    zalo_oa_access_token = fields.Char(
        string='Zalo OA Access Token',
        config_parameter='ai_sales_support.zalo_oa_access_token',
        help='Zalo Official Account access token'
    )
    
    zalo_app_id = fields.Char(
        string='Zalo App ID',
        config_parameter='ai_sales_support.zalo_app_id',
        help='Zalo application ID'
    )
    
    zalo_app_secret = fields.Char(
        string='Zalo App Secret',
        config_parameter='ai_sales_support.zalo_app_secret',
        help='Zalo application secret key'
    )
    
    # AI Sales Behavior Settings
    auto_contact_suppliers = fields.Boolean(
        string='Auto Contact Suppliers',
        default=True,
        config_parameter='ai_sales_support.auto_contact_suppliers',
        help='Automatically contact suppliers when stock is insufficient'
    )
    
    supplier_response_timeout = fields.Integer(
        string='Supplier Response Timeout (minutes)',
        default=30,
        config_parameter='ai_sales_support.supplier_response_timeout',
        help='How long to wait for supplier response before timeout'
    )
    
    default_markup_percentage = fields.Float(
        string='Default Markup Percentage',
        default=20.0,
        config_parameter='ai_sales_support.default_markup_percentage',
        help='Default markup percentage to apply to supplier prices'
    )
    
    # System Prompt for AI
    ai_system_prompt = fields.Text(
        string='AI System Prompt',
        default="""You are an AI sales assistant for a Vietnamese company. Your role is to:
1. Analyze product inquiries from sales team
2. Check inventory and pricing information
3. Generate professional quotations
4. Communicate with suppliers when needed

Always respond in Vietnamese and be professional and helpful.
When stock is insufficient, clearly indicate that you will contact suppliers.
Provide accurate pricing and availability information.""",
        config_parameter='ai_sales_support.ai_system_prompt',
        help='System prompt to guide AI behavior'
    )

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        return res

    def set_values(self):
        super(ResConfigSettings, self).set_values()