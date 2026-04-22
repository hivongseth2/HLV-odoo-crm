from odoo import fields, models

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    milwaukee_base_url = fields.Char(
        string='Milwaukee Base URL',
        config_parameter='milwaukee.base_url',
        default='http://localhost:3000'
    )
