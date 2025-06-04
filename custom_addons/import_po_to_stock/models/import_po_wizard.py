from odoo import models, fields
import base64
import tempfile
import pandas as pd

class ImportPOWizard(models.TransientModel):
    _name = "import.po.wizard"
    _description = "Import PO into Stock"

    file = fields.Binary("Excel File", required=True)
    filename = fields.Char("File Name")

    def action_import(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(base64.b64decode(self.file))
            tmp_path = tmp.name

        df = pd.read_excel(tmp_path)
        df.fillna("", inplace=True)

        for index, row in df.iterrows():
            product_code = str(row.get("Mã hàng", "")).strip()
            qty = float(row.get("Số lượng", 0))
            warehouse_name = str(row.get("Kho", "")).strip()

            if not product_code or not warehouse_name or qty <= 0:
                continue

            product = self.env['product.product'].search([('default_code', '=', product_code)], limit=1)
            location = self.env['stock.location'].search([('complete_name', 'ilike', warehouse_name)], limit=1)

            if product and location:
                self.env['stock.quant'].create({
                    'product_id': product.id,
                    'location_id': location.id,
                    'inventory_quantity': qty,
                })
