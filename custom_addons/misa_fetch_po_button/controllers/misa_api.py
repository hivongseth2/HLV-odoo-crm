# controllers/misa_api.py
# -*- coding: utf-8 -*-
import logging, json
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

class MisaApiSaleOrder(http.Controller):

    @http.route('/api/misa/sale_order/resync', type='json', auth='none', methods=['POST'], csrf=False)
    def api_misa_sale_order_resync(self, **payload):
        """
        Public API: không yêu cầu login.
        Body JSON ví dụ:
        {
          "token": "hoanglongvu",
          "misa_order_id": "abc-123",
          "warehouse_id": 1,
          "create_when_missing": true
        }
        """

        # ---- Lấy JSON body an toàn (nếu Postman gửi sai Content-Type vẫn bắt được) ----
        try:
            # Với type='json', Odoo sẽ parse vào **payload; nếu rỗng thì tự đọc lại từ raw.
            if not payload:
                try:
                    body = request.httprequest.get_json(force=False, silent=True)
                except Exception:
                    body = None
                if body is None:
                    raw = (request.httprequest.data or b'').decode('utf-8', errors='ignore')
                    try:
                        body = json.loads(raw) if raw else {}
                    except Exception:
                        body = {}
                payload = dict(body or {})
        except Exception:
            # Không chặn flow vì chỉ là logging/phòng thủ
            pass

        # ---- Lấy token từ body hoặc header ----
        raw_token = (payload.get("token") if isinstance(payload, dict) else None) \
                    or request.httprequest.headers.get('X-MISA-Token')
        token = (raw_token or "").strip()

        # Log nhẹ xem server nhận gì (không dùng request.jsonrequest nữa)
        _logger.info("MISA API /resync payload=%r token=%r", payload, token)

        # ---- Token check (có thể thay bằng system parameter nếu bạn muốn) ----
        expected = request.env['ir.config_parameter'].sudo().get_param('misa.api.token') or "hoanglongvu"

        # loại zero-width nếu có
        try:
            import re
            token = re.sub(r'[\u200B-\u200D\uFEFF]', '', token)
            expected = re.sub(r'[\u200B-\u200D\uFEFF]', '', expected)
        except Exception:
            pass

        if token != expected:
            return {"ok": False, "error": "invalid_token", "message": "Token không hợp lệ."}

        # ---- Lấy tham số nghiệp vụ ----
        misa_order_id = payload.get("misa_order_id")
        warehouse_id = payload.get("warehouse_id")
        create_when_missing = payload.get("create_when_missing", True)

        # ---- Chạy dưới quyền admin ----
        admin_user = request.env.ref("base.user_admin", raise_if_not_found=False)
        if not admin_user:
            return {"ok": False, "error": "admin_not_found"}

        try:
            env_admin = request.env(user=admin_user).sudo()
            result = env_admin["sale.order"].api_resync_by_misa(
                misa_order_id=misa_order_id,
                warehouse_id=warehouse_id,
                create_when_missing=bool(create_when_missing),
            )
            return result
        except Exception as e:
            _logger.exception("MISA API /resync exception: %s", e)
            return {"ok": False, "error": "exception", "message": str(e)}
