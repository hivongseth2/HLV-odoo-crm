from odoo import models, fields, api
import base64
import pandas as pd
from io import BytesIO

class ProductImportWizard(models.TransientModel):
    _name = 'product.import.wizard'
    _description = 'Wizard to import products from Excel'

    file = fields.Binary("Excel File", required=True)
    filename = fields.Char("File Name")

    def action_import(self):
        data = base64.b64decode(self.file)
        df = pd.read_excel(BytesIO(data))

        def safe_get(row, key):
            return row[key] if key in row and pd.notnull(row[key]) else False

        for _, row in df.iterrows():
            default_code = safe_get(row, 'Mã')
            name = safe_get(row, 'Tên')
            uom_name = safe_get(row, 'Đơn vị tính chính')
            categ_name = safe_get(row, 'Nhóm VTHH')
            origin = safe_get(row, 'Nguồn gốc')
            ptype = safe_get(row, 'Tính chất')
            barcode = safe_get(row, 'Mã vạch') if 'Mã vạch' in row else False

            price_cost = safe_get(row, 'Đơn giá mua gần nhất') or 0.0
            price_sale = safe_get(row, 'Đơn giá bán 1') or 0.0
            tax_value = safe_get(row, 'Thuế suất GTGT')

            if not default_code or not name:
                continue

            uom = self.env['uom.uom'].search([('name', '=', uom_name)], limit=1)
            if not uom:
                uom = self.env['uom.uom'].create({'name': uom_name, 'category_id': 1})

            categ = self.env['product.category'].search([('name', '=', categ_name)], limit=1)
            if not categ:
                categ = self.env['product.category'].create({'name': categ_name})

            product_type = 'product' if str(ptype).strip().lower() == 'hàng hóa' else 'service'

            taxes = self.env['account.tax'].search([('amount', '=', float(tax_value)), ('type_tax_use', '=', 'sale')], limit=1)
            if not taxes and tax_value:
                taxes = self.env['account.tax'].create({
                    'name': f'VAT {tax_value}%',
                    'amount': float(tax_value),
                    'type_tax_use': 'sale',
                })

            existing = self.env['product.template'].search([('default_code', '=', default_code)], limit=1)
            if existing:
                continue

            vals = {
                'name': name,
                'default_code': default_code,
                'uom_id': uom.id,
                'uom_po_id': uom.id,
                'categ_id': categ.id,
                'type': product_type,
                'standard_price': price_cost,
                'list_price': price_sale,
                'barcode': barcode or False,
                'x_origin': origin,
                'taxes_id': [(6, 0, taxes.ids)] if taxes else False,
            }
            self.env['product.template'].create(vals)
