from odoo import fields, models

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    milwaukee_base_url = fields.Char(
        string='Milwaukee Base URL',
        config_parameter='milwaukee.base_url',
        default='http://localhost:3000'
    )
    milwaukee_master_key = fields.Char(
        string='Master API Key',
        config_parameter='milwaukee.master_key',
        default='milwaukee-master-odoo-secret-2026'
    )
