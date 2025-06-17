import requests
from odoo import models, fields, _
from odoo.exceptions import UserError
from datetime import datetime
import logging

_logger = logging.getLogger(__name__)

class SaleAPIImportWizard(models.TransientModel):
    _name = "sale.api.import.wizard"
    _description = "Import Sale Orders from MISA API"

    date_from = fields.Date(string="From Date", required=True, default=fields.Date.today)
    date_to = fields.Date(string="To Date", required=True, default=fields.Date.today)

    def button_import(self):
        token = self._get_token()
        data = self._fetch_orders(token)
        self._process_orders(data)
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def _get_token(self):
        url = "https://crmconnect.misa.vn/api/v2/Account"
        payload = {
            "client_id": "odoo",
            "client_secret": "iqFXzEnjLIpuSTdkwFhuvj1Y4jsD9xHrUzZvF81bO8="
        }
        resp = requests.post(url, json=payload)
        resp.raise_for_status()
        return resp.json().get('access_token')

    def _fetch_orders(self, token):
        url = "https://crmconnect.misa.vn/api/v2/SaleOrders"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        params = {"fromDate": self.date_from.strftime("%Y-%m-%d"), "toDate": self.date_to.strftime("%Y-%m-%d")}
        resp = requests.get(url, headers=headers, params=params)
        resp.raise_for_status()
        return resp.json().get('data', [])

    def _process_orders(self, items):
        for o in items:
            ref = o.get("orderCode")
            if not ref: continue
            if self.env['sale.order'].search([('name','=',ref)], limit=1):
                _logger.warning("Đơn %s đã tồn tại, bỏ qua", ref)
                continue

            partner = self.env['res.partner'].search([('name','=',o.get("customerName"))], limit=1) or \
                      self.env['res.partner'].create({
                          'name': o.get("customerName"),
                          'ref': o.get("customerCode"),
                      })
            user = self.env['res.users'].search([('name','=',o.get("employeeName"))], limit=1) or self.env.user
            team = self.env['crm.team'].search([('name','=',o.get("departmentName"))], limit=1) or \
                   self.env['crm.team'].create({'name': o.get("departmentName")})
            wh = self.env['stock.warehouse'].search([], limit=1)
            dt = datetime.strptime(o.get("orderDate"), "%Y-%m-%dT%H:%M:%S")

            order = self.env['sale.order'].create({
                'name': ref, 'partner_id': partner.id, 'partner_shipping_id': partner.id,
                'date_order': dt, 'user_id': user.id,
                'team_id': team.id, 'warehouse_id': wh.id,
            })
            order.action_confirm()

            for d in o.get("saleOrderDetails", []):
                qty = d.get("quantity") or 0
                up = d.get("unitPrice") or 0
                disc = d.get("discountAmount") or 0
                taxamt = d.get("taxAmount") or 0

                gross = qty * up
                disc_pct = (disc / gross * 100) if gross else 0
                taxable = gross - disc
                vat_pct = round((taxamt / taxable * 100), 2) if taxable else 0

                tax = self.env['account.tax'].search([
                    ('amount','=',vat_pct), ('price_include','=',True), ('type_tax_use','=','sale')], limit=1) or \
                      self.env['account.tax'].create({
                          'name': f'Thuế {vat_pct}%', 'amount': vat_pct,
                          'price_include': True, 'type_tax_use': 'sale',
                      })

                prod = self.env['product.product'].search([('default_code','=',d.get("inventoryItemCode"))], limit=1) or \
                       self.env['product.product'].create({
                           'name': d.get("inventoryItemName") or d.get("inventoryItemCode"),
                           'default_code': d.get("inventoryItemCode"),
                           'type':'consu', 'list_price': up,
                       })
                uom = self.env['uom.uom'].search([('name','=',d.get("unitName"))], limit=1)

                self.env['sale.order.line'].create({
                    'order_id': order.id, 'product_id': prod.id,
                    'product_uom_qty': qty, 'price_unit': up,
                    'discount': disc_pct, 'tax_id': [(6,0,[tax.id])],
                    'product_uom': uom.id if uom else None,
                })
