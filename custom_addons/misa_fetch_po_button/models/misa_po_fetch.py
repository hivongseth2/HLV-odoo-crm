
from odoo import models, fields, _
import requests
import logging
import json

_logger = logging.getLogger(__name__)

class MisaPOFetch(models.TransientModel):
    _name = "misa.po.fetch"
    _description = "MISA PO Fetch"
    def action_fetch_po(self):
        access_token = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1aWQiOiJkZjBjYjMzYi1iMTM5LTQ5ZjUtYWMyNC1mOWY4NjBiNGU5ODciLCJ1bmEiOiJOR1VZRU5USEFOSExVQU4iLCJhdXQiOiIwIiwidWVtIjoibmd1eWVubHVhbjEzMDMwMUBnbWFpbC5jb20iLCJuYmYiOjE3NTA0MDcwNjIsImV4cCI6MTc1MDQ5MzQ5MCwiaWF0IjoxNzUwNDA3MDYyLCJpc3MiOiJNSVNBSlNDIn0.dISLn9Vd2j5rRDWHi0wFDyfdDlk4-PeDIDHpp-5Dh4Q"
        headers = {
            "Authorization": f"{access_token}",
            "Content-Type": "application/json",
            "x-device": "04aadfced5b04995ecfacb0a7da5c50c",
            "X-MISA-Context": json.dumps({
                    "TenantId":"47ab503b-99d5-4eb8-aa11-24927abb3585",
                    "TenantCode":"3R2PY2F4",
                    "DatabaseId":"f4b18d63-6c99-4a53-b974-f6208e84fced",
                    "BranchId":"53a073a0-5381-4493-820f-51ea32ebe990",
                    "WorkingBook":0,
                    "Language":"vi",
                    "IncludeDependentBranch":False,
                    "SessionId":"ssdf0cb33bb13949f5ac24f9f860b4e987.04aadfced5b04995ecfacb0a7da5c50c.f4b18d636c994a53b974f6208e84fced.638860290625845472",
                    "DBType":1,
                    "AuthType":0,
                    "AmisSessionId":"NAA3AGEAYgA1ADAAMwBiADkAOQBkADUANABlAGIAOABhAGEAMQAxADIANAA5ADIANwBhAGIAYgAzADUAOAA1ADAAYgBlADEAMgAyAGIAMAA3AGIANAAyADQAZAAzAGMAOQA1AGQAYQBjAGEANAAxADYAZQAxADIAMwBhADAAYQA=",
                    "HasAgent":False,
                    "UserType":1,
                    "art":0,
                    "UserId":"df0cb33b-b139-49f5-ac24-f9f860b4e987",
                    "isc":False
                })

        }

        payload = {
            "filter": [
                {
                    "property": 3654,
                    "value": "2025-05-31T17:00:00.00Z",
                    "operator": 10,
                    "operand": 1,
                    "data_type": 3
                }
            ],
            "loadMode": 2,
            "pageIndex": 1,
            "pageSize": 20,
            "sort": json.dumps([
                {"property": 3654, "desc": True, "data_type": 3, "operand": 1},
                {"property": 3972, "desc": True, "data_type": 3, "operand": 1},
                {"property": 4018, "desc": True, "data_type": 1, "operand": 1}
            ]),
            "summaryColumns": [5080, 5730, 5128, 5059],
            "useSp": False,
            "view": 40
        }


        response = requests.post(
            "https://actapp.misa.vn/g1/api/pu/v1/pu_list/paging_filter_v2",
            headers=headers,
            json=payload
        )

        _logger.info("Raw status: %s", response.status_code)
        _logger.info("Response text: %s", response.text)
        _logger.info("Headers: %s", response.headers)

        if response.status_code == 200:
            # _logger.info("GET PO: %s", response.json())
            _logger.info("FULL RESPONSE: %s", json.dumps(response.json(), indent=2))


            # po_data_list = response.json().get("data", [])
            po_data_list = response.json().get("Data", {}).get("PageData", [])

            for po in po_data_list:
                refid = po.get("refid")
                supplier_name = po.get("account_object_name")
                refno = po.get("refno_finance", "PO-MISA")
                memo = po.get("journal_memo", "")
                partner = self._get_or_create_partner(supplier_name)

                po_rec = self.env["purchase.order"].create({
                    "partner_id": partner.id,
                    "origin": refno,
                    # "note": memo,
                })
                # Gọi chi tiết đơn hàng
                detail_payload = {
                    "columns": [2157, 1355, 4670, 1195, 1065, 5683, 5274, 3870, 5279, 308],
                    "filter": [{
                        "property": 3993,
                        "operator": 7,
                        "operand": 1,
                        "value": refid,
                        "data_type": 10
                    }],
                    "loadMode": 2,
                    "pageIndex": 1,
                    "pageSize": 20,
                    "sort": json.dumps([{"property": 4555, "desc": False, "data_type": 4, "operand": 1}]),
                    "summaryColumns": [3488, 3870, 308, 1844, 2241],
                    "useSp": False,
                    "view": 35
                }
                detail_res = requests.post("https://actapp.misa.vn/g1/api/pu/v1/pu_voucher/get_paging_detail",
                                        headers=headers, json=detail_payload)
                if detail_res.status_code != 200:
                    _logger.warning("Không lấy được chi tiết PO %s", refid)
                    continue
                for line in detail_res.json().get("Data", {}).get("PageData", []):
                    code = line.get("inventory_item_code", "unknown_code").strip()
                    name = line.get("description", "unknown product").strip()
                    qty = float(line.get("quantity", 1))
                    price = float(line.get("unit_price", 0))
                    unit_name = line.get("unit_name", "Cái").strip()
                    
                    uom = self._get_or_create_uom(unit_name)
                    product = self._get_or_create_product(code, name, uom)
                    
                    _logger.info("📦 Đang gọi API chi tiết PO %s", refid)
                    _logger.info("👉 Payload gửi đi: %s", json.dumps(detail_payload, indent=2))
                    _logger.info("📨 Response text: %s", detail_res.text)
                    if product and product.uom_id.category_id.id == uom.category_id.id:
                        self.env["purchase.order.line"].create({
                            "order_id": po_rec.id,
                            "name": name,
                            "product_id": product.id,
                            "product_qty": qty,
                            "product_uom": uom.id,
                            "price_unit": price
                        })
                    else:
                        _logger.warning("❌ Bỏ qua sản phẩm %s vì UOM không khớp loại.", code)


    def _get_or_create_partner(self, name):
        partner = self.env["res.partner"].search([("name", "=", name)], limit=1)
        if not partner:
            partner = self.env["res.partner"].create({"name": name, "supplier_rank": 1})
        return partner
    def _get_or_create_uom(self, name):
        # Ưu tiên dùng đúng đơn vị tên "Cái" đã có trong hệ thống (tránh tạo mới)
        uom = self.env['uom.uom'].search([('name', '=', name)], limit=1)
        if uom:
            return uom

        # Nếu không có thì tạo mới trong cùng category "Đơn vị"
        cat = self.env['uom.category'].search([('name', 'ilike', 'đơn vị')], limit=1)
        if not cat:
            cat = self.env['uom.category'].create({'name': 'Đơn vị'})

        uom = self.env['uom.uom'].create({
            'name': name,
            'category_id': cat.id,
            'uom_type': 'reference',
            'rounding': 1.0,
        })
        return uom

    def _get_or_create_product(self, code, name, uom):
        product = self.env["product.product"].search([("default_code", "=", code)], limit=1)
        if product:
            # Kiểm tra xem UOM hiện tại có cùng category không
            if product.uom_id.category_id.id != uom.category_id.id:
                _logger.warning("⚠️ UOM không cùng loại. Bỏ qua sản phẩm %s", code)
                return None
            return product

        tmpl = self.env["product.template"].create({
            "name": name,
            "default_code": code,
            "type": "consu",
            "uom_id": uom.id,
            "uom_po_id": uom.id,
            "purchase_ok": True,
            "sale_ok": False,
            "is_storable": True,
        })
        return tmpl.product_variant_id
