import requests 
from odoo import models, fields, api
from datetime import datetime, timedelta
from dateutil import parser  # để xử lý ISO datetime
import logging

_logger = logging.getLogger(__name__)

class SaleApiImportWizard(models.TransientModel):
    _name = 'sale.api.import.wizard'
    _description = 'Import Sale Orders from MISA API'

    from_date = fields.Date(string="Từ ngày", required=True)
    to_date = fields.Date(string="Đến ngày", required=True)

    def action_import_from_api(self):
        token_url = "https://crmconnect.misa.vn/api/v2/Account"
        orders_url = "https://crmconnect.misa.vn/api/v2/SaleOrders"
        payload = {
            "client_id": "odoo",
            "client_secret": "iqFXzEnjLIpuSTdkwFhuvj1Y4jsD9zXHrUzZvF81bO8="
        }
        headers = {"Content-Type": "application/json"}

        try:
            res = requests.post(token_url, json=payload, headers=headers)
            _logger.info("🔐 Token response: %s", res.text)
            res.raise_for_status()
            token = res.json().get("data")
            if not token:
                raise Exception("❌ MISA không trả về access_token")
        except Exception as e:
            raise Exception(f"Lỗi lấy token từ MISA: {e}")

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        page = 1
        page_size = 20

        # Cập nhật ngày kết thúc là cuối ngày
        end_datetime = datetime.combine(self.to_date, datetime.max.time())

        while page <= 100:
            params = {
                "page": page,
                "pageSize": page_size,
                "orderBy": "sale_order_date",
                "isDescending": True
            }
            try:
                response = requests.get(orders_url, headers=headers, params=params)
                _logger.info("📦 Order page %s: %s", page, response.text)
                response.raise_for_status()
                orders = response.json().get("data", [])
            except Exception as e:
                raise Exception(f"Lỗi khi lấy đơn hàng từ API MISA: {e}")

            if not orders:
                break

            for order in orders:
                order_date_str = order.get("created_date")
                order_date = parser.parse(order_date_str).replace(tzinfo=None) if order_date_str else fields.Datetime.now()

                if order_date < datetime.combine(self.from_date, datetime.min.time()) or order_date > end_datetime:
                    continue

                if order.get("stock_name") != "HCM":
                    continue

                order_ref = order.get("sale_order_no")
                customer_name = order.get("account_name")
                amount = float(order.get("sale_order_amount", 0.0))

                if not order_ref or not customer_name:
                    _logger.warning("⛔ Thiếu mã đơn hoặc tên khách hàng trong đơn hàng: %s", order)
                    continue

                partner = self.env['res.partner'].search([('name', '=', customer_name)], limit=1)
                if not partner:
                    partner = self.env['res.partner'].create({'name': customer_name})

                existing_order = self.env['sale.order'].search([('name', '=', order_ref)], limit=1)
                if existing_order:
                    _logger.info("🔁 Bỏ qua đơn hàng đã tồn tại: %s", order_ref)
                    continue

                sale_order = self.env['sale.order'].create({
                    'name': order_ref,
                    'partner_id': partner.id,
                    'date_order': order_date,
                    'amount_total': amount,
                })

                for line in order.get("sale_order_product_mappings", []):
                    product_code = line.get("product_code")
                    description = line.get("description") or product_code
                    qty = float(line.get("amount", 1))
                    price_unit = float(line.get("price", 0))
                    discount_percent = float(line.get("discount_percent", 0))
                    uom_name = line.get("unit", "Cái").strip()

                    category = self.env['uom.category'].search([('name', '=', 'Unit')], limit=1)
                    if not category:
                        category = self.env['uom.category'].create({'name': 'Unit'})

                    uom = self.env['uom.uom'].search([
                        ('name', '=', uom_name),
                        ('category_id', '=', category.id)
                    ], limit=1)

                    if not uom:
                        existing_ref = self.env['uom.uom'].search([
                            ('category_id', '=', category.id),
                            ('uom_type', '=', 'reference')
                        ], limit=1)

                        uom = self.env['uom.uom'].create({
                            'name': uom_name,
                            'category_id': category.id,
                            'uom_type': 'smaller' if existing_ref else 'reference',
                            'factor': 1.0,
                            'factor_inv': 1.0,
                            'rounding': 1.0,
                        })

                    product = self.env['product.product'].search([('default_code', '=', product_code)], limit=1)
                    if not product:
                        template = self.env['product.template'].create({
                            'name': description,
                            'default_code': product_code,
                            'type': 'consu',
                            'uom_id': uom.id,
                            'uom_po_id': uom.id,
                            'list_price': price_unit,
                            'purchase_ok': False,
                            'sale_ok': False,
                            'is_storable': True,
                        })
                        product = template.product_variant_id

                    self.env['sale.order.line'].create({
                        'order_id': sale_order.id,
                        'product_id': product.id,
                        'name': description,
                        'product_uom_qty': qty,
                        'price_unit': price_unit,
                        'discount': discount_percent
                    })

                sale_order.action_confirm()
                _logger.info("✅ Đã tạo và xác nhận đơn hàng: %s cho %s", order_ref, customer_name)

            page += 1

        return {'type': 'ir.actions.act_window_close'}
