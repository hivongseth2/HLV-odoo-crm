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
        odoo_utils = self.env['odoo.utils']  # Initialize OdooUtils
        misa_utils = self.env['misa.api.utils']
        token = misa_utils._fetch_login_crm_token()  # Get MISA token

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

        start_datetime = datetime.combine(self.from_date, datetime.min.time())
        end_datetime = datetime.combine(self.to_date, datetime.max.time())

        while page <= 50:
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
                order_date = parser.parse(order_date_str).replace(tzinfo=None) if order_date_str else datetime.now()

                if order_date < start_datetime:
                    continue
                if order_date > end_datetime:
                    _logger.info("🛑 Gặp đơn vượt quá ngày, dừng vòng lặp: %s", order.get("sale_order_no"))
                    return {'type': 'ir.actions.act_window_close'}

                product_lines = order.get("sale_order_product_mappings", [])
                filtered_lines = [l for l in product_lines if l.get("stock_name") == "HCM"]
                if not filtered_lines:
                    continue

                order_ref = order.get("sale_order_no")
                id = order.get("id")
                customer_name = order.get("account_name")
                amount = float(order.get("sale_order_amount", 0.0))

                if not order_ref or not customer_name:
                    _logger.warning("⛔ Thiếu mã đơn hoặc tên khách hàng trong đơn hàng: %s", order)
                    continue

                # Use OdooUtils to get or create partner
                partner = odoo_utils._get_or_create_partner(customer_name)

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

                for line in filtered_lines:
                    product_code = line.get("product_code")
                    description = line.get("description") or product_code
                    qty = float(line.get("amount", 1))
                    price_unit = float(line.get("price", 0))
                    discount_percent = float(line.get("discount_percent", 0))
                    uom_name = (line.get("unit") or "Cái").strip()

                    # Xử lý sản phẩm combo
                    if "+" in product_code:
                        combo_codes = product_code.split("+")
                        combo_products = []
                        all_exist = True

                        for code in combo_codes:
                            code = code.strip()
                            product = self.env["product.product"].search([("default_code", "=", code)], limit=1)
                            if not product:
                                _logger.warning("❌ Không tìm thấy sản phẩm con: %s trong combo %s", code, product_code)
                                all_exist = False
                                break
                            combo_products.append(product)

                        if all_exist:
                            for product in combo_products:
                                self.env['sale.order.line'].create({
                                    'order_id': sale_order.id,
                                    'product_id': product.id,
                                    'name': f"{description} - [{product.default_code}]",
                                    'product_uom_qty': qty,
                                    'price_unit': price_unit / len(combo_products),  # chia giá nếu cần
                                    'discount': discount_percent
                                })
                        else:
                            _logger.error("🚫 Bỏ qua combo vì thiếu sản phẩm con: %s", product_code)
                    else:
                        product = odoo_utils._get_or_create_product(
                            code=product_code,
                            name=description,
                            unit_name=uom_name,
                            cost=price_unit,
                            product_type="consu",
                            purchase_ok=False,
                            sale_ok=False
                        )

                        self.env['sale.order.line'].create({
                            'order_id': sale_order.id,
                            'product_id': product.id,
                            'name': description,
                            'product_uom_qty': qty,
                            'price_unit': price_unit,
                            'discount': discount_percent
                        })


                # Lấy DeliveryOrderNumber từ API MISA
                delivery_order_number = misa_utils.get_delivery_number(id,order_ref,token)
                _logger.info("📋 Delivery Order Number: %s", delivery_order_number)

                # Xác nhận đơn hàng để tạo stock.picking
                sale_order.action_confirm()
                _logger.info("✅ Đã tạo và xác nhận đơn hàng: %s cho %s", order_ref, customer_name)

                # Gán DeliveryOrderNumber làm mã phiếu pick
                pickings = sale_order.picking_ids
                if pickings:
                    picking = pickings[0]  # Lấy phiếu pick đầu tiên
                    # Kiểm tra tính duy nhất trước khi gán
                    existing_picking = self.env['stock.picking'].search([('name', '=', delivery_order_number)], limit=1)
                    if existing_picking:
                        _logger.warning("⚠️ Mã phiếu pick %s đã tồn tại, tạo mã mới: %s", delivery_order_number, f"{delivery_order_number}_{picking.id}")
                        picking.name = f"{delivery_order_number}_{picking.id}"
                    else:
                        picking.name = delivery_order_number
                    _logger.info("📦 Đã gán mã phiếu pick: %s cho đơn hàng %s", picking.name, order_ref)

            page += 1
        return {'type': 'ir.actions.act_window_close'}