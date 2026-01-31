from odoo import fields, models

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    product_crawler_openai_api_key = fields.Char(
        string='OpenAI API Key',
        config_parameter='product_crawler.openai_api_key'
    )
    product_crawler_openai_model = fields.Selection(
        [('gpt-4o-mini', 'GPT-4o Mini'), 
         ('gpt-3.5-turbo', 'GPT-3.5 Turbo'),
         ('gpt-4o', 'GPT-4o')],
        string='OpenAI Model',
        default='gpt-4o-mini',
        config_parameter='product_crawler.openai_model'
    )
