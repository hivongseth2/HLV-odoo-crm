import requests
import json

class SaleApiImportWizard(models.TransientModel):
    _name = 'sale.api.import.wizard'
    _description = 'Import Sale Orders from MISA API'

    from_date = fields.Date(string="Từ ngày")
    to_date = fields.Date(string="Đến ngày")

    def action_fetch_from_misa(self):
        # 1. Lấy token truy cập
        token_url = "https://crmconnect.misa.vn/api/v2/Account"
        payload = {
            "client_id": "odoo",
            "client_secret": "iqFXzEnjLIpuSTdkwFhuvj1Y4jsD9zXHrUzZvF81bO8="
        }

        try:
            res = requests.post(token_url, json=payload)
            res.raise_for_status()
            access_token = res.json().get("access_token")
        except Exception as e:
            raise UserError(f"Không lấy được token từ MISA: {str(e)}")

        # 2. Gọi API lấy đơn hàng
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        order_url = "https://crmconnect.misa.vn/api/v2/SaleOrders"

        data = {
            "page_size": 100,
            "page_num": 1,
            "from_date": self.from_date.strftime("%Y-%m-%d") if self.from_date else None,
            "to_date": self.to_date.strftime("%Y-%m-%d") if self.to_date else None,
        }

        try:
            order_res = requests.post(order_url, headers=headers, json=data)
            order_res.raise_for_status()
            orders = order_res.json().get("data", [])
        except Exception as e:
            raise UserError(f"Lỗi khi gọi API lấy đơn hàng: {str(e)}")

        # 3. Hiện cảnh báo demo để bạn kiểm tra
        raise UserError(f"Đã lấy được {len(orders)} đơn hàng từ MISA (demo, chưa xử lý).")

        # (Bạn có thể thêm code xử lý đơn hàng ở đây nếu muốn import thẳng)
