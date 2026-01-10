
from odoo import fields, models, api, _


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    barcode_generate = fields.Boolean("Generate Barcode EAN13 From Product")
    option_generated = fields.Selection([('date', 'Generate Barcode EAN13 through Current Date'),
                                        ('random', 'Generate Barcode EAN13 through Random Number')],string='Generate Barcode Option',default='date')

    @api.model
    def default_get(self, fields_list):
        res = super(ResConfigSettings, self).default_get(fields_list)
        if self.search([], limit=1, order="id desc").barcode_generate == 1:
            search_option = self.search([], limit=1, order="id desc").option_generated
            res.update({'barcode_generate': 1,
                        'option_generated':search_option})
        return res

