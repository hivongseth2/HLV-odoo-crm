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
        rows = list(sheet.iter_rows(min_row=5, values_only=True))  # Bắt đầu sau tiêu đề (dòng 4)

        for row in rows:
            order_ref = str(row[80]).strip()            # CC – Mã đơn hàng
            customer_code = str(row[6]).strip()         # G – Mã khách hàng
            customer_name = str(row[7]).strip()         # H – Tên khách hàng
            order_date = row[0]                          # A – Ngày hạch toán
            salesperson_name = str(row[74]).strip()     # BW – Tên nhân viên bán hàng
            sales_team_name = str(row[76]).strip()      # BY – Tên đơn vị kinh doanh

            if not order_ref or not customer_name:
                continue

            # Partner
            partner = self.env['res.partner'].search([('name', '=', customer_name)], limit=1)
            if not partner:
                partner = self.env['res.partner'].create({
                    'name': customer_name,
                    'ref': customer_code,
                })
            partner_shipping = partner

            # Salesperson
            salesperson = self.env['res.users'].search([('name', '=', salesperson_name)], limit=1)
            if not salesperson:
                salesperson = self.env.user

            # Sales team
            sales_team = self.env['crm.team'].search([('name', '=', sales_team_name)], limit=1)
            if not sales_team:
                sales_team = self.env['crm.team'].create({'name': sales_team_name or "Kinh doanh không rõ"})

            warehouse = self.env['stock.warehouse'].search([], limit=1)

            if isinstance(order_date, datetime):
                order_date = order_date.strftime('%Y-%m-%d')
            else:
                try:
                    order_date = datetime.strptime(str(order_date).strip(), "%d/%m/%Y").strftime('%Y-%m-%d')
                except Exception:
                    order_date = fields.Date.today()

            existing_order = self.env['sale.order'].search([('name', '=', order_ref)], limit=1)
            if existing_order:
                _logger.warning("⛔ Đơn hàng %s đã tồn tại. Bỏ qua.", order_ref)
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

        # Tạo dòng sản phẩm cho đơn hàng
        for row in rows:
            order_ref = str(row[80]).strip()
            if order_ref not in sale_orders:
                continue

            product_code = str(row[16]).strip()
            product_desc = str(row[17]).strip()
            quantity = row[25]
            total_qty = row[36]           # Tổng SL bán theo ĐVC (AK)
            unit_price = row[37]          # Đơn giá theo ĐVC (AL)
            total_price = row[39]         # Doanh số bán (AN)
            discount = row[45]            # Chiết khấu (AS)
            tax_value = row[63]           # Thuế GTGT tiền (BL)
            total_payment = row[65]       # Tổng thanh toán (BN)
            uom_name = str(row[32]).strip()

            if not product_code or not quantity or not unit_price:
                continue

            # Tính phần trăm chiết khấu
            discount_percent = 0.0
            try:
                gross_total = float(unit_price) * float(total_qty or 0)
                if discount and gross_total:
                    discount_percent = (float(discount) / gross_total) * 100
            except:
                discount_percent = 0.0

            # Tính phần trăm thuế
            # Tính phần trăm thuế từ số tiền thuế
            tax = False
            try:
                taxable_amount = gross_total - float(discount or 0)
                if tax_value and taxable_amount:
                    vat_percent = (float(tax_value) / taxable_amount) * 100
                    vat_percent = round(vat_percent, 2)  # ✅ Không làm tròn bội số 5

                    tax = self.env['account.tax'].search([
                        ('amount', '=', vat_percent),
                        ('type_tax_use', '=', 'sale'),
                        ('price_include', '=', True)  # ✅ Phải khớp luôn kiểu giá
                    ], limit=1)

                    if not tax:
                        tax = self.env['account.tax'].create({
                            'name': f'Thuế {vat_percent:.2f}%',
                            'amount': vat_percent,
                            'type_tax_use': 'sale',
                            'price_include': True,  # ✅ Thuế đã bao gồm trong đơn giá
                        })
            except:
                tax = False



            # Tạo sản phẩm nếu chưa có
            product = self.env['product.product'].search([('default_code', '=', product_code)], limit=1)
            if not product:
                product = self.env['product.product'].create({
                    'name': product_desc or product_code,
                    'default_code': product_code,
                    'type': 'consu',
                    'list_price': unit_price,
                })

            # Đơn vị tính
            uom = self.env['uom.uom'].search([('name', '=', uom_name)], limit=1)
            if not uom:
                uom = self.env['uom.uom'].search([('name', '=', 'Units')], limit=1)

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
