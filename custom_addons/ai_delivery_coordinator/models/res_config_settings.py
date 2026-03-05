# -*- coding: utf-8 -*-
from odoo import models, fields

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    openai_api_key = fields.Char(string='OpenAI API Key', config_parameter='ai_delivery_coordinator.openai_api_key')
    openai_model_delivery = fields.Char(string='OpenAI Model', config_parameter='ai_delivery_coordinator.openai_model_delivery', default='gpt-4o')
    track_asia_api_key = fields.Char(string='Track-Asia API Key', config_parameter='ai_delivery_coordinator.track_asia_api_key')
    rapidapi_key = fields.Char(string='RapidAPI Key', config_parameter='ai_delivery_coordinator.rapidapi_key')
    delivery_warehouse_id = fields.Many2one(
        'stock.warehouse', string='Kho xuất phát (tính khoảng cách)',
        config_parameter='ai_delivery_coordinator.warehouse_id',
    )
    ai_custom_prompt = fields.Text(
        string='Prompt AI Tùy Chỉnh', 
        config_parameter='ai_delivery_coordinator.ai_custom_prompt',
        default="Bạn là chuyên gia logistics Việt Nam. Hãy phân tuyến giao hàng tối ưu dựa trên Toạ độ GPS, khoảng cách và thông tin chi tiết các món hàng."
    )
