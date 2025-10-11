# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

class MisaApiSaleOrder(http.Controller):

    @http.route('/api/misa/sale_order/resync', type='json', auth='none', methods=['POST'], csrf=False)
    def api_misa_sale_order_resync(self, **payload):
        """
        Public API: không yêu cầu login
        Body JSON ví dụ:
        {
          "token": "hoanglongvu",
          "misa_order_id": "abc-123",
          "warehouse_id": 1,              // optional
          "create_when_missing": true     // optional
        }
        """
        token = (payload.get("token") or "").strip()
        misa_order_id = payload.get("misa_order_id")
        warehouse_id = payload.get("warehouse_id")
        create_when_missing = payload.get("create_when_missing", True)

        # === 1️⃣ Kiểm tra token ===
        if token != "hoanglongvu":
            return {
                "ok": False,
                "error": "invalid_token",
                "message": "Token không hợp lệ."
            }

        # === 2️⃣ Xác định user admin ===
        admin_user = request.env.ref("base.user_admin", raise_if_not_found=False)
        if not admin_user:
            return {"ok": False, "error": "admin_not_found"}

        try:
            # === 3️⃣ Gọi model method với sudo(admin) ===
            env_admin = request.env(user=admin_user).sudo()
            result = env_admin["sale.order"].api_resync_by_misa(
                misa_order_id=misa_order_id,
                warehouse_id=warehouse_id,
                create_when_missing=bool(create_when_missing),
            )
            return result

        except Exception as e:
            return {
                "ok": False,
                "error": "exception",
                "message": str(e)
            }
