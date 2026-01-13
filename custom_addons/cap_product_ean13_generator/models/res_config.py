
from odoo import fields, models, api, _


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    barcode_generate = fields.Boolean("Tạo mã vạch EAN13 từ sản phẩm")
    option_generated = fields.Selection([('date', 'Tạo mã EAN13 theo ngày hiện tại'),
                                        ('random', 'Tạo mã EAN13 ngẫu nhiên')],string='Tùy chọn tạo mã vạch',default='date')

    @api.model
    def default_get(self, fields_list):
        res = super(ResConfigSettings, self).default_get(fields_list)
        if self.search([], limit=1, order="id desc").barcode_generate == 1:
            search_option = self.search([], limit=1, order="id desc").option_generated
            res.update({'barcode_generate': 1,
                        'option_generated':search_option})
        return res

