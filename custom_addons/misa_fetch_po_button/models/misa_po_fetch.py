
from odoo import models, fields, _
import requests
import logging

_logger = logging.getLogger(__name__)

class MisaPOFetch(models.TransientModel):
    _name = "misa.po.fetch"
    _description = "MISA PO Fetch"

    def action_fetch_po(self):
        access_token = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1aWQiOiJkZjBjYjMzYi1iMTM5LTQ5ZjUtYWMyNC1mOWY4NjBiNGU5ODciLCJ1bmEiOiJOR1VZRU5USEFOSExVQU4iLCJhdXQiOiIwIiwidWVtIjoibmd1eWVubHVhbjEzMDMwMUBnbWFpbC5jb20iLCJuYmYiOjE3NTA0MDcwNjIsImV4cCI6MTc1MDQ5MzQ5MCwiaWF0IjoxNzUwNDA3MDYyLCJpc3MiOiJNSVNBSlNDIn0.dISLn9Vd2j5rRDWHi0wFDyfdDlk4-PeDIDHpp-5Dh4Q"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "x-device": "04aadfced5b04995ecfacb0a7da5c50c",

            "X-MISA-Context": '{"TenantId":"47ab503b-99d5-4eb8-aa11-24927abb3585","TenantCode":"3R2PY2F4","DatabaseId":"f4b18d63-6c99-4a53-b974-f6208e84fced","BranchId":"53a073a0-5381-4493-820f-51ea32ebe990","WorkingBook":0,"Language":"vi","IncludeDependentBranch":"false","SessionId":"ssdf0cb33bb13949f5ac24f9f860b4e987.04aadfced5b04995ecfacb0a7da5c50c.f4b18d636c994a53b974f6208e84fced.638860290625845472","DBType":1,"AuthType":0,"AmisSessionId":"NAA3AGEAYgA1ADAAMwBiADkAOQBkADUANABlAGIAOABhAGEAMQAxADIANAA5ADIANwBhAGIAYgAzADUAOAA1ADAAYgBlADEAMgAyAGIAMAA3AGIANAAyADQAZAAzAGMAOQA1AGQAYQBjAGEANAAxADYAZQAxADIAMwBhADAAYQA=","HasAgent":false,"UserType":1,"art":0,"UserId":"df0cb33b-b139-49f5-ac24-f9f860b4e987","isc":false}',
        }

        payload = {
            "filter": [],
            "loadMode": 2,
            "pageIndex": 1,
            "pageSize": 10,
            "sort": "",
            "summaryColumns": [],
            "useSp": False,
            "view": 40
        }

        response = requests.post(
            "https://actapp.misa.vn/g1/api/pu/v1/pu_list/paging_filter_v2",
            headers=headers,
            json=payload
        )

        if response.status_code == 200:
            po_data_list = response.json().get("data", [])
            for po_data in po_data_list:
                supplier_name = po_data.get("account_object_name")
                product_name = po_data.get("journal_memo", "SP MISA")
                qty = 1
                price_unit = float(po_data.get("total_amount_oc", 1.0))
                code = po_data.get("refno", "SP-MISA")
                uom_name = "Cái"

                # Tìm hoặc tạo NCC
                partner = self.env["res.partner"].search([("name", "=", supplier_name)], limit=1)
                if not partner:
                    partner = self.env["res.partner"].create({
                        "name": supplier_name,
                        "supplier_rank": 1,
                    })
                    _logger.info("Created new supplier: %s", supplier_name)

                # Tìm hoặc tạo ĐVT
                uom_category = self.env['uom.category'].search([('name', 'ilike', 'đơn vị')], limit=1)
                if not uom_category:
                    uom_category = self.env['uom.category'].create({'name': 'Đơn vị'})
                uom = self.env['uom.uom'].search([
                    ('name', 'ilike', uom_name),
                    ('category_id', '=', uom_category.id)
                ], limit=1)
                if not uom:
                    uom = self.env['uom.uom'].create({
                        'name': uom_name,
                        'category_id': uom_category.id,
                        'uom_type': 'reference',
                        'rounding': 1.0,
                    })

                # Tìm hoặc tạo sản phẩm
                product = self.env["product.product"].search([("default_code", "=", code)], limit=1)
                if not product:
                    tmpl = self.env["product.template"].create({
                        "name": product_name,
                        "default_code": code,
                        "type": "product",
                        "uom_id": uom.id,
                        "uom_po_id": uom.id,
                        "purchase_ok": True,
                        "sale_ok": False,
                        'is_storable': True,
                    })
                    product = tmpl.product_variant_id

                # Tạo đơn hàng mua
                self.env["purchase.order"].create({
                    "partner_id": partner.id,
                    "order_line": [(0, 0, {
                        "name": product_name,
                        "product_id": product.id,
                        "product_qty": qty,
                        "product_uom": uom.id,
                        "price_unit": price_unit
                    })]
                })
                _logger.info("Created PO for supplier: %s", supplier_name)
