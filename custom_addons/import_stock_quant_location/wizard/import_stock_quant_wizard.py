
from odoo import models, fields, api
import pandas as pd
import base64
import tempfile

class ImportStockQuantWizard(models.TransientModel):
    _name = "import.stock.quant.wizard"
    _description = "Import tồn kho theo vị trí"

    file = fields.Binary(string="File Excel", required=True)
    filename = fields.Char(string="Tên tập tin")

    def action_import(self):
        if not self.file:
            return

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(base64.b64decode(self.file))
            tmp.seek(0)
            df = pd.read_excel(tmp.name)

        for _, row in df.iterrows():
            product_code = row.get("Mã sản phẩm")
            location_name = row.get("Vị trí")
            quantity = row.get("Số lượng", 0)

            if not product_code or not location_name:
                continue

            product = self.env["product.product"].search([("default_code", "=", str(product_code))], limit=1)
            location = self.env["stock.location"].search([("name", "=", str(location_name))], limit=1)

            if product and location:
                self.env["stock.quant"].create({
                    "product_id": product.id,
                    "location_id": location.id,
                    "inventory_quantity": quantity,
                })
