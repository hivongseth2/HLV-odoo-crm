
from odoo import models, fields
import requests

class MisaPOFetch(models.TransientModel):
    _name = "misa.po.fetch"
    _description = "MISA PO Fetch"

    def action_fetch_po(self):
        access_token = "<your_access_token>"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-MISA-Context": '{\"TenantId\":\"abc\",\"TenantCode\":\"XYZ\"}'  # sửa cho đúng
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
            data = response.json().get("data", [])
            for po in data:
                self.env["purchase.order"].create({
                    "partner_id": 1,  # Sửa ID NCC đúng theo dữ liệu của bạn
                    "order_line": [(0, 0, {
                        "name": po.get("journal_memo", "PO từ MISA"),
                        "product_id": 1,  # Sửa ID sản phẩm theo bạn
                        "product_qty": 1,
                        "price_unit": float(po.get("total_amount_oc", 1.0))
                    })]
                })
