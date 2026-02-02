from odoo import models, fields, api

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    product_crawler_openai_api_key = fields.Char(
        string="OpenAI API Key",
        config_parameter='product_crawler.openai_api_key',
        help="API Key for OpenAI (Mr. GPT) integration."
    )
    
    product_crawler_openai_model = fields.Char(
        string="OpenAI Model",
        config_parameter='product_crawler.openai_model',
        default='gpt-4o-mini',
        help="Model to use (e.g. gpt-4o-mini, gpt-4-turbo)."
    )

    product_crawler_batch_size = fields.Integer(
        string="Cron Batch Size",
        config_parameter='product_crawler.batch_size',
        default=10,
        help="Number of products to crawl per scheduled run."
    )

    product_crawler_auto_crawl = fields.Boolean(
        string="Enable Auto Crawl Cron",
        config_parameter='product_crawler.auto_crawl',
        help="If checked, the background job will automatically crawl products in the queue."
    )
