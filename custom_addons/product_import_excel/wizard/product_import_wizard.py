
from odoo import models, fields, api
import base64
import pandas as pd
from io import BytesIO

class ProductImportWizard(models.TransientModel):
    _name = 'product.import.wizard'
    _description = 'Import Products from Excel'

    file = fields.Binary(string="Excel File", required=True)
    filename = fields.Char(string="File Name")

    def action_import(self):
        if not self.file:
            return

        stream = BytesIO(base64.b64decode(self.file))
        df = pd.read_excel(stream, sheet_name=0)

        for _, row in df.iterrows():
            code = row.get('Mã')
            name = row.get('Tên')
            uom_name = row.get('Đơn vị tính chính')
            barcode = row.get('Mã vạch', False)
            price_purchase = row.get('Đơn giá mua gần nhất', 0.0)
            price_sale_1 = row.get('Đơn giá bán 1', 0.0)
            x_vat = row.get('Thuế suất GTGT', 0.0)
            x_origin = row.get('Nguồn gốc', 'unknown')
            type_raw = row.get('Tính chất', '').strip().lower()

            type_map = {'hàng hóa': 'product', 'dịch vụ': 'service'}
            ptype = type_map.get(type_raw, 'product')

            uom = self.env['uom.uom'].search([('name', '=', uom_name)], limit=1)
            if not uom:
                uom = self.env['uom.uom'].create({'name': uom_name, 'category_id': 1})

            existing = self.env['product.template'].search([('default_code', '=', code)], limit=1)
            if existing:
                continue

            self.env['product.template'].create({
                'name': name,
                'default_code': code,
                'barcode': barcode if barcode else False,
                'type': ptype,
                'list_price': price_sale_1 or 0.0,
                'standard_price': price_purchase or 0.0,
                'uom_id': uom.id,
                'uom_po_id': uom.id,
                'x_vat': x_vat,
                'x_origin': x_origin
            })
