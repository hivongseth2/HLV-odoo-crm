from odoo import models, fields
import base64
import tempfile
import pandas as pd
import math

class ProductStockImportWizard(models.TransientModel):
    _name = "product.stock.import.wizard"
    _description = "Import stock quantities from Excel"

    file = fields.Binary(string="Excel File", required=True)
    filename = fields.Char(string="File Name")

    def action_import(self):
        if not self.file:
            return

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(base64.b64decode(self.file))
            tmp.seek(0)
            df = pd.read_excel(tmp.name)

        for _, row in df.iterrows():
            code = str(row.get("Mã sản phẩm")).strip()
            location_name = str(row.get("Vị trí")).strip()
            quantity = row.get("Số lượng tồn", 0)

            product = self.env["product.product"].search([("default_code", "=", code)], limit=1)
            location = self.env["stock.location"].search([("complete_name", "=", location_name)], limit=1)

            if not product or not location:
                continue

            existing_quant = self.env["stock.quant"].search([
                ("product_id", "=", product.id),
                ("location_id", "=", location.id)
            ], limit=1)

            if existing_quant:
                existing_quant.quantity = quantity
            else:
                self.env["stock.quant"].create({
                    "product_id": product.id,
                    "location_id": location.id,
                    "quantity": quantity,
                })