import base64
import openpyxl
from odoo import models, fields, api
from odoo.exceptions import UserError
from datetime import datetime
from io import BytesIO

class SaleImportWizard(models.TransientModel):
    _name = 'sale.import.wizard'
    _description = 'MISA Sale Order Import Wizard'

    file = fields.Binary(string='Excel File', required=True)
    file_name = fields.Char(string='File Name')

    def action_import(self):
        if not self.file:
            raise UserError('Please upload an Excel file.')

        file_data = base64.b64decode(self.file)
        workbook = openpyxl.load_workbook(filename=BytesIO(file_data))

        danh_sach_sheet = workbook['Danh sách']
        hang_hoa_sheet = workbook['Bảng hàng hóa']

        sale_orders = {}
        for row in danh_sach_sheet.iter_rows(min_row=2, values_only=True):
            order_ref = row[1]
            customer_name = row[2]
            order_date = row[4]
            salesperson_name = row[6]
            sales_team_name = row[7]
            country = row[10]
            state = row[11]
            city = row[12]
            street = row[13]

            if not order_ref or not customer_name:
                continue

            partner = self.env['res.partner'].search([('name', '=', customer_name)], limit=1)
            if not partner:
                partner = self.env['res.partner'].create({
                    'name': customer_name,
                    'country_id': self.env['res.country'].search([('name', '=', country)], limit=1).id or None,
                    'state_id': self.env['res.country.state'].search([('name', '=', state)], limit=1).id or None,
                    'city': city,
                    'street': street,
                })

            partner_shipping = partner

            salesperson = self.env['res.users'].search([('name', '=', salesperson_name)], limit=1)
            if not salesperson:
                salesperson = self.env.user

            sales_team = self.env['crm.team'].search([('name', '=', sales_team_name)], limit=1)
            if not sales_team:
                sales_team = self.env['crm.team'].create({'name': sales_team_name})

            warehouse = self.env['stock.warehouse'].search([], limit=1)

            if isinstance(order_date, datetime):
                order_date = order_date.strftime('%Y-%m-%d')

            sale_order = self.env['sale.order'].create({
                'name': order_ref,
                'partner_id': partner.id,
                'partner_shipping_id': partner_shipping.id,
                'date_order': order_date,
                'user_id': salesperson.id,
                'team_id': sales_team.id,
                'warehouse_id': warehouse.id,
            })
            sale_order.action_confirm()
            sale_orders[order_ref] = sale_order

        for row in hang_hoa_sheet.iter_rows(min_row=2, values_only=True):
            order_ref = row[0]
            product_code = row[1]
            product_desc = row[2]
            quantity = row[6]
            unit_price = row[8]
            tax_rate = row[14]
            uom_name = row[5]
            discount = row[12]

            if order_ref not in sale_orders:
                continue

            if not product_code or not quantity or not unit_price:
                continue

            product = self.env['product.product'].search([('default_code', '=', product_code)], limit=1)
            if not product:
                product = self.env['product.product'].create({
                    'name': product_desc or product_code,
                    'default_code': product_code,
                    'type': 'product',
                    'list_price': unit_price,
                })

            tax = False
            if tax_rate:
                try:
                    tax_value = float(str(tax_rate).replace('%', '').strip())
                    tax = self.env['account.tax'].search([('amount', '=', tax_value), ('type_tax_use', '=', 'sale')], limit=1)
                    if not tax:
                        tax = self.env['account.tax'].create({
                            'name': f'Tax {tax_value}%',
                            'amount': tax_value,
                            'type_tax_use': 'sale',
                        })
                except:
                    pass

            uom = self.env['uom.uom'].search([('name', '=', uom_name)], limit=1)
            if not uom:
                uom = self.env['uom.uom'].search([('name', '=', 'Units')], limit=1)

            discount_percent = 0.0
            if discount and unit_price and quantity:
                try:
                    discount_percent = (float(discount) / (float(unit_price) * float(quantity))) * 100
                except:
                    discount_percent = 0.0

            self.env['sale.order.line'].create({
                'order_id': sale_orders[order_ref].id,
                'product_id': product.id,
                'name': product_desc or product.name,
                'product_uom_qty': float(quantity),
                'price_unit': float(unit_price),
                'tax_id': [(6, 0, tax.ids)] if tax else False,
                'product_uom': uom.id,
                'discount': discount_percent,
            })