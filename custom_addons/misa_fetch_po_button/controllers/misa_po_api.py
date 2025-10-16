# controllers/misa_po_api.py
# -*- coding: utf-8 -*-
import logging
import json
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class MisaApiPurchaseOrder(http.Controller):

    @http.route('/api/misa/purchase_order/sync', type='json', auth='none', methods=['POST'], csrf=False)
    def api_misa_purchase_order_sync(self, **payload):
        """
        Public API: không yêu cầu login.
        Body JSON ví dụ:
        {
          "token": "hoanglongvu",
          "po_code": "DMH12218",
          "create_when_missing": true
        }
        
        Trả về:
        {
          "ok": true/false,
          "res_id": 123,
          "name": "DMH12218",
          "action": "created" | "updated" | "deleted" | "not_found" | "orphaned",
          "detail": "Chi tiết kết quả"
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

        # Log nhẹ xem server nhận gì
        _logger.info("MISA PO API /sync payload=%r token=%r", payload, token)

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
        po_code = payload.get("po_code")
        create_when_missing = payload.get("create_when_missing", True)
        delete_when_missing = payload.get("delete_when_missing", True)

        if not po_code:
            return {"ok": False, "error": "missing_po_code", "message": "Thiếu mã đơn hàng (po_code)"}

        # ---- Chạy dưới quyền admin ----
        admin_user = request.env.ref("base.user_admin", raise_if_not_found=False)
        if not admin_user:
            return {"ok": False, "error": "admin_not_found"}

        try:
            env_admin = request.env(user=admin_user)

            result = env_admin["purchase.order"].api_sync_po_by_code(
                po_code=po_code,
                create_when_missing=bool(create_when_missing),
                delete_when_missing=bool(delete_when_missing),
            )
            return result
        except Exception as e:
            _logger.exception("MISA PO API /sync exception: %s", e)
            return {"ok": False, "error": "exception", "message": str(e)}
