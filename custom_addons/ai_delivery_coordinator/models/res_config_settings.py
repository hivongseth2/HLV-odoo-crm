# -*- coding: utf-8 -*-
from odoo import models, fields

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    openai_api_key = fields.Char(string='OpenAI API Key', config_parameter='ai_delivery_coordinator.openai_api_key')
    openai_model_delivery = fields.Char(string='OpenAI Model', config_parameter='ai_delivery_coordinator.openai_model_delivery', default='gpt-4o')
    rapidapi_key = fields.Char(string='RapidAPI Key', config_parameter='ai_delivery_coordinator.rapidapi_key')
    delivery_warehouse_id = fields.Many2one(
        'stock.warehouse', string='Kho xuất phát (tính khoảng cách)',
        config_parameter='ai_delivery_coordinator.warehouse_id',
    )
