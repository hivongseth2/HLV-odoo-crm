from odoo import models, fields
import base64
import tempfile
import pandas as pd
import math

class ProductStockImport(models.TransientModel):
    _name = "product.stock.import"
    _description = "Import tồn kho theo vị trí"

    file = fields.Binary(string="Excel File", required=True)
    filename = fields.Char(string="File Name")

    def action_import_stock(self):
        if not self.file:
            return

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(base64.b64decode(self.file))
            tmp.seek(0)
            df = pd.read_excel(tmp.name)

        for _, row in df.iterrows():
            product_code = str(row.get('Mã SP')).strip()
            location_name = str(row.get('Vị trí')).strip()
            qty = row.get('Số lượng', 0.0)

            if not product_code or not location_name:
                continue

            product = self.env['product.product'].search([('default_code', '=', product_code)], limit=1)
            if not product:
                continue

            location = self.env['stock.location'].search([('name', '=', location_name)], limit=1)
            if not location:
                location = self.env['stock.location'].create({'name': location_name, 'usage': 'internal'})

            self.env['stock.quant']._update_available_quantity(product, location, qty)
