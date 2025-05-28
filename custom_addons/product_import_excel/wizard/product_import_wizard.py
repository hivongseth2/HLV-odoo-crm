from odoo import models, fields, api
import base64
import tempfile
import pandas as pd

class ProductImportWizard(models.TransientModel):
    _name = "product.import.wizard"
    _description = "Wizard to import product from Excel"

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
            name = row.get('Tên hàng hóa')
            default_code = row.get('Mã')
            barcode = row.get('Mã vạch', False)
            x_origin = row.get('Nguồn gốc', '')
            x_group = row.get('Nhóm VTHH', '')
            x_property = row.get('Tính chất', '')
            vat = row.get('Thuế suất GTGT', 10)
            cost_price = row.get('Đơn giá mua gần nhất', 0.0)
            price1 = row.get('Đơn giá bán 1', 0.0)
            price2 = row.get('Đơn giá bán 2', 0.0)
            price3 = row.get('Đơn giá bán 3', 0.0)

            values = {
                "name": name,
                "default_code": default_code,
                "barcode": barcode,
                "standard_price": cost_price,
                "list_price": price1,
                "x_origin": x_origin,
                "x_group": x_group,
                "x_property": x_property,
                "taxes_id": [(6, 0, [self._get_tax_id(vat)])],
            }

            self.env["product.template"].create(values)

    def _get_tax_id(self, vat):
        tax = self.env['account.tax'].search([('amount', '=', vat), ('type_tax_use', '=', 'sale')], limit=1)
        return tax.id if tax else False