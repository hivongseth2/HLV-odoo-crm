from odoo import models

class Http(models.AbstractModel):
    _inherit = 'ir.http'

    def session_info(self):
        result = super().session_info()
        base_url = self.env['ir.config_parameter'].sudo().get_param('milwaukee.base_url', 'http://localhost:3000')
        result['milwaukee_base_url'] = base_url
        return result
