import base64
import openpyxl
from odoo import models, fields, api
from odoo.exceptions import UserError
from datetime import datetime
from io import BytesIO
import logging
_logger = logging.getLogger(__name__)

class SaleImportWizard(models.TransientModel):
    _name = 'sale.import.wizard'
    _description = 'MISA Sale Order Import Wizard HLV'

    file = fields.Binary(string='Excel File', required=True)
    file_name = fields.Char(string='File Name')


def action_import(self):
    if not self.file:
        raise UserError('Please upload an Excel file.')

    file_data = base64.b64decode(self.file)
    workbook = openpyxl.load_workbook(filename=BytesIO(file_data), data_only=True)
    sheet = workbook["SỔ CHI TIẾT BÁN HÀNG"]

    sale_orders = {}
    rows = list(sheet.iter_rows(min_row=4, values_only=True))  # Dữ liệu bắt đầu từ dòng 4 (index = 3)

    for row in rows:
        order_ref = row[2]
        customer_name = row[7]
        order_date = row[0]
        sales_team_name = row[122]

        if not order_ref or not customer_name:
            continue

        partner = self.env['res.partner'].search([('name', '=', customer_name)], limit=1)
        if not partner:
            partner = self.env['res.partner'].create({
                'name': customer_name,
            })

        partner_shipping = partner

        salesperson = self.env.user  # Sheet này không có tên người bán

        sales_team = self.env['crm.team'].search([('name', '=', sales_team_name)], limit=1)
        if not sales_team:
            sales_team = self.env['crm.team'].create({'name': sales_team_name or "Chi nhánh không xác định"})

        warehouse = self.env['stock.warehouse'].search([], limit=1)

        if isinstance(order_date, datetime):
            order_date = order_date.strftime('%Y-%m-%d')

        existing_order = self.env['sale.order'].search([('name', '=', order_ref)], limit=1)
        if existing_order:
            _logger.warning("⛔ Đơn hàng %s đã tồn tại. Bỏ qua không tạo lại.", order_ref)
            continue

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

    for row in rows:
        order_ref = row[2]
        product_code = row[16]
        product_desc = row[17]
        quantity = row[25]
        unit_price = row[30]
        uom_name = row[32]
        # discount = 0  # File này chưa thấy có cột chiết khấu
        # tax_rate = 0  # File này chưa thấy có cột thuế
        
        if discount and unit_price and quantity:
            try:
                discount_percent = (float(discount) / (float(unit_price) * float(quantity))) * 100
            except:
                discount_percent = 0.0
                
        tax = False
        if tax_value and unit_price and quantity:
            try:
                vat_percent = (float(tax_value) / (float(unit_price) * float(quantity))) * 100
                vat_percent = round(vat_percent, 0)  # Làm tròn về 5%, 10%...
                tax = self.env['account.tax'].search([
                    ('amount', '=', vat_percent),
                    ('type_tax_use', '=', 'sale')
                ], limit=1)
                if not tax:
                    tax = self.env['account.tax'].create({
                        'name': f'Thuế {vat_percent}%',
                        'amount': vat_percent,
                        'type_tax_use': 'sale',
                    })
            except:
                tax = False



        if order_ref not in sale_orders:
            continue

        if not product_code or not quantity or not unit_price:
            continue



        product = self.env['product.product'].search([('default_code', '=', product_code)], limit=1)
        if not product:
            product = self.env['product.product'].create({
                'name': product_desc or product_code,
                'default_code': product_code,
                'type': 'consu',
                'list_price': unit_price,
            })

        tax = False
        if tax_rate:
            try:
                tax_value = float(str(tax_rate).replace('%', '').strip())
                tax = self.env['account.tax'].search([
                    ('amount', '=', tax_value),
                    ('type_tax_use', '=', 'sale')
                ], limit=1)
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
