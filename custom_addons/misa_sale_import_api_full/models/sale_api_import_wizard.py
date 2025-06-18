import requests
from odoo import models, fields, api
from datetime import datetime, timedelta
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

        headers = {
            "Content-Type": "application/json"
        }

        token = None
        try:
            res = requests.post(token_url, json=payload, headers=headers)
            _logger.info("🔁 MISA token response: %s", res.text)
            res.raise_for_status()

            token = res.json().get("data")
    
        except Exception as e:
            raise Exception(f"Lỗi lấy token: {e}")

        if not token:
            raise Exception("Không lấy được access_token từ MISA.")

        headers = {"Authorization": f"Bearer {token}"}
        params = {
            "from_date": self.from_date.strftime('%Y-%m-%d'),
            "to_date": self.to_date.strftime('%Y-%m-%d')
        }

        try:
            response = requests.get(orders_url, headers=headers, params=params)
            response.raise_for_status()
            orders = response.json().get("data", [])
        except Exception as e:
            raise Exception(f"Lỗi khi lấy đơn hàng từ API MISA: {e}")

        for order in orders:
            order_ref = order.get("order_code")
            customer_name = order.get("customer_name")
            order_date = order.get("order_date")
            if not order_ref or not customer_name:
                continue

            partner = self.env["res.partner"].search([("name", "=", customer_name)], limit=1)
            if not partner:
                partner = self.env["res.partner"].create({"name": customer_name})

            existing_order = self.env["sale.order"].search([("name", "=", order_ref)], limit=1)
            if existing_order:
                continue

            sale_order = self.env["sale.order"].create({
                "name": order_ref,
                "partner_id": partner.id,
                "date_order": order_date,
            })
            sale_order.action_confirm()

            for line in order.get("lines", []):
                product_code = line.get("product_code")
                qty = float(line.get("quantity", 1))
                price_unit = float(line.get("price_unit", 0))
                product = self.env["product.product"].search([("default_code", "=", product_code)], limit=1)
                if not product:
                    product = self.env["product.product"].create({
                        "name": product_code,
                        "default_code": product_code,
                        "list_price": price_unit,
                    })

                self.env["sale.order.line"].create({
                    "order_id": sale_order.id,
                    "product_id": product.id,
                    "name": product.name,
                    "product_uom_qty": qty,
                    "price_unit": price_unit,
                })