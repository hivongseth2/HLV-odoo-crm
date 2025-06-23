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
                "property": 4658,
                "value": 3,
                "operator": 7,
                "operand": 1,
                "data_type": 4
                },
                {
                "property": 3972,
                "value": "2025-05-31T17:00:00.00Z",
                "operator": 10,
                "operand": 1,
                "data_type": 3
                },
                {
                "property": 3972,
                "value": "2025-06-23T01:28:34.842Z",
                "operator": 12,
                "operand": 1,
                "data_type": 3
                }
            ],
            "loadMode": 2,
            "pageIndex": 1,
            "pageSize": 20,
            "sort": "[{\"property\":3972,\"desc\":true,\"data_type\":3,\"operand\":1},{\"property\":4008,\"desc\":true,\"data_type\":1,\"operand\":1}]",
            "summaryColumns": [5039, 5104, 247],
            "useSp": False,
            "view": 2
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
                "columns": [2157, 1355, 2161, 4670, 5683, 5274, 3870, 3895, 5279, 308, 5364, 5350, 3404, 2358],
                "filter": [
                    {
                    "property": 3993,
                    "operator": 7,
                    "operand": 1,
                    "value": refid,
                    "data_type": 10
                    }
                ],
                "loadMode": 2,
                "pageIndex": 1,
                "pageSize": 20,
                "sort": "[{\"property\":4555,\"desc\":false,\"data_type\":4,\"operand\":1}]",
                "summaryColumns": [3488, 3870, 3895, 3896, 308, 5350],
                "useSp": False,
                "view": 92
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
                vat_rate = float(line.get("vat_rate", 0))

                # uom = self._get_or_create_uom(unit_name)
                product = self._get_or_create_product(code, name, unit_name)

                self.env["purchase.order.line"].create({
                    "order_id": po_rec.id,
                    "name": name,
                    "product_id": product.id,
                    "product_qty": qty,
                    "product_uom": uom.id,
                    "price_unit": price
                })


    def _get_or_create_partner(self, name):
        partner = self.env["res.partner"].search([("name", "=", name)], limit=1)
        if not partner:
            partner = self.env["res.partner"].create({"name": name, "supplier_rank": 1})
        return partner

    def _get_or_create_uom(self, name):
        name = name.strip().title()  # ✅ CHUẨN HÓA TÊN

        UoM = self.env['uom.uom']
        UoMCat = self.env['uom.category']

        # Tìm UoM theo tên
        uom = UoM.search([('name', '=', name)], limit=1)
        if uom:
            return uom

        # Tìm hoặc tạo category
        cat = UoMCat.search([('name', 'ilike', 'đơn vị')], limit=1)
        if not cat:
            cat = UoMCat.create({'name': 'Đơn vị'})

        # Kiểm tra xem đã có reference UoM trong category chưa
        ref_uom = UoM.search([
            ('category_id', '=', cat.id),
            ('uom_type', '=', 'reference')
        ], limit=1)

        if not ref_uom:
            # Nếu chưa có, đây sẽ là UoM chuẩn
            uom_type = 'reference'
            factor = 1.0
        else:
            # Nếu đã có, tạo UoM phụ thuộc (same name but scaled)
            uom_type = 'bigger'  # hoặc 'smaller', tùy ngữ cảnh
            factor = 1.0  # cần xác định hợp lý, ví dụ: 1 cái = 1 ref

        return UoM.create({
            'name': name,
            'category_id': cat.id,
            'uom_type': uom_type,
            'factor_inv': factor,
            'rounding': 1.0,
        })


    def _get_or_create_product(self, code, name, uom):
        product = self.env["product.product"].search([("default_code", "=", code)], limit=1)
        if product:
            _logger.info("🔁 Tìm thấy sản phẩm %s. Dùng UOM gốc: %s", code, product.uom_id.name)
            return product
        uom = self._get_or_create_uom(unit_name)


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
        _logger.info("🆕 Tạo sản phẩm %s với UOM: %s", code, uom.name)

        return tmpl.product_variant_id
