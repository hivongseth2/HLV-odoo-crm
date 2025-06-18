from odoo import models, fields, api
from datetime import datetime

class SaleApiImportWizard(models.TransientModel):
    _name = 'sale.api.import.wizard'
    _description = 'Wizard to Import Sale Orders from MISA API'

    from_date = fields.Date(string="Từ ngày")
    to_date = fields.Date(string="Đến ngày")

    def action_import(self):
        # TODO: Gọi API MISA và xử lý dữ liệu
        pass
