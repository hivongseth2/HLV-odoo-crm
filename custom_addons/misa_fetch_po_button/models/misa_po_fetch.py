from odoo import models, fields, _ 
import requests
import logging
import json
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)

class MisaPOFetch(models.TransientModel):
    _name = "misa.po.fetch"
    _description = "MISA PO Fetch"

    def _get_misa_token(self):
        login_url = "https://amisapp.misa.vn/APIS/AuthenAPI/api/Account/login"
        payload = {
            "UserName": "Hoanglongvuco@gmail.com",
            "Password": "Hoanglongvu@2025"
        }
        headers = {"content-type": "application/json"}
        response = requests.post(login_url, json=payload, headers=headers)
        _logger.warning("Đăng nhập MISA với user: %s", response.json())
        if response.status_code != 200:
            raise Exception("❌ Lỗi đăng nhập MISA")
        data = response.json().get("Data", {})
        return data.get("AccessToken", {}).get("Token", "")
    
    
    



    def _fetch_po_list(self, headers, payload):
        url = "https://actapp.misa.vn/g1/api/pu/v1/pu_list/paging_filter_v2"
        response = requests.post(url, headers=headers, json=payload)
        _logger.info("Response text: %s", response.text)
        if response.status_code == 401:
            _logger.warning("🔁 Token hết hạn, đang đăng nhập lại...")
            new_token = self._get_misa_token()
            _logger.info("🔑 Đăng nhập thành công, token mới: %s", new_token)
            headers["Authorization"] = f"Bearer {new_token}"
            response = requests.post(url, headers=headers, json=payload)
        return response

    def action_fetch_po(self):
        access_token = self._get_misa_token()
        today_utc = (datetime.utcnow() - timedelta(hours=7)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + "Z"

        headers = {
                "Authorization": f"Bearer {access_token}",
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
                    "value": today_utc,
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

        response = self._fetch_po_list(headers, payload)
        _logger.info("Raw status: %s", response.status_code)
        _logger.info("Response text: %s", response.text)

        if response.status_code != 200:
            return

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
            })

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

            detail_res = requests.post(
                "https://actapp.misa.vn/g1/api/pu/v1/pu_voucher/get_paging_detail",
                headers=headers, json=detail_payload
            )

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
        uom = self.env['uom.uom'].search([('name', '=', name)], limit=1)
        if uom:
            return uom

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
