import requests
from odoo import models, fields, api
from datetime import datetime, timedelta
from dateutil import parser  # để xử lý ISO datetime
import logging
from dateutil.parser import parse

_logger = logging.getLogger(__name__)

class SaleApiImportWizard(models.TransientModel):
    _name = 'sale.api.import.wizard'
    _description = 'Import Sale Orders from MISA API'

    from_date = fields.Date(string="Từ ngày", required=True)
    to_date = fields.Date(string="Đến ngày", required=True)


    def action_import_from_api(self):
        odoo_utils = self.env['odoo.utils']  
        misa_utils = self.env['misa.api.utils']
        misa_config = self.env['misa.config']

        crm_token = misa_utils._fetch_login_crm_token() 

        token_url = "https://crmconnect.misa.vn/api/v2/Account"
        orders_url = "https://amisapp.misa.vn/crm/g2/api/business/SaleOrder/Grid"
        order_detail_url = "https://amisapp.misa.vn/crm/g2/api/business/SaleOrder/DataSubPaging"

        sale_headers = misa_config.get_crm_header(crm_token)

        start_datetime = datetime.combine(self.from_date, datetime.min.time())
        end_datetime = datetime.combine(self.to_date, datetime.max.time())

        page = 1
        while True:
            payload = misa_config.get_crm_sale_order_payload(start_datetime,end_datetime, page)
            try:
                response = requests.post(orders_url, headers=sale_headers, json=payload) 
                response.raise_for_status()
                orders = response.json().get("Data", [])
            except Exception as e:
                
                raise Exception(f"Lỗi khi lấy đơn hàng từ API MISA: {e} {payload}")

            for order in orders:

            # có order thì đi gọi lấy danh sách sản phẩm trong product đó 
                id = order.get("ID")
                payload = misa_config.get_crm_sale_order_detail_payload(id)


                product_lines = misa_utils.get_list_product_by_order_crm(order_detail_url,sale_headers,payload)
                
                _logger.warning("📦 Order product_lines %s",  product_lines)

                filtered_lines = [l for l in product_lines if l.get("StockIDText") == "HCM"]
                if not filtered_lines:
                    continue

                order_ref = order.get("SaleOrderNo")
                customer_name = order.get("AccountIDText") or order.get("SaleOrderName")

                amount = float(order.get("SaleOrderAmount", 0.0))
                # order_date = order.get("SaleOrderDate")
                order_date = parse(order.get("SaleOrderDate")).replace(tzinfo=None)

                # detail_order_payload = misa_config.get_list_product_by_order_crm(id)

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
                
                
                product_list = misa_utils
                

                for line in filtered_lines:
                    product_code = line.get("ProductIDText")
                    description = line.get("Description") or product_code
                    qty = float(line.get("Amount", 1))
                    price_unit = float(line.get("Price", 0))
                    discount_percent = float(line.get("DiscountPercent", 0))
                    uom_name = (line.get("UnitIDText") or "Cái").strip()

                    if "+" in product_code:
                        combo_codes = product_code.split("+")
                        combo_products = []
                        all_exist = True

                        for code in combo_codes:
                            code = code.strip()
                            product = self.env["product.product"].search([("default_code", "=", code)], limit=1)

                            if not product:
                                _logger.warning("🔍 Không thấy %s trong hệ thống, thử gọi MISA để tạo mới...", code)
                                try:
                                    tmpl = odoo_utils.get_misa_product(crm_token, code)
                                    product = tmpl.product_variant_id
                                    _logger.info("✅ Đã tạo mới sản phẩm con %s từ MISA", code)
                                except Exception as e:
                                    _logger.error("🚫 Không tạo được sản phẩm %s từ MISA: %s", code, str(e))
                                    all_exist = False
                                    break

                            if product:
                                combo_products.append(product)
                            else:
                                all_exist = False
                                break

                        if all_exist:
                            for product in combo_products:
                                self.env['sale.order.line'].create({
                                    'order_id': sale_order.id,
                                    'product_id': product.id,
                                    'name': f"{description} - [{product.default_code}]",
                                    'product_uom_qty': qty,
                                    'price_unit': price_unit / len(combo_products),
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
                delivery_order_number = misa_utils.get_delivery_number(sale_order_id=id,order_ref=order_ref,token = crm_token)
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
                        _logger.warning("⚠️ Mã phiếu pick %s đã tồn tại, NEXT tạo mã mới: %s", delivery_order_number, f"{delivery_order_number}_{picking.id}")
                        # picking.name = f"{delivery_order_number}_{picking.id}"
                    else:
                        picking.name = delivery_order_number
                    _logger.info("📦 Đã gán mã phiếu pick: %s cho đơn hàng %s", picking.name, order_ref)
            if len(orders) < 20:
                            break
            page += 1
        return {'type': 'ir.actions.act_window_close'}