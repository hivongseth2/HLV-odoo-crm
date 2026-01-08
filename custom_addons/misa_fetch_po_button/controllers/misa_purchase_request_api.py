# controllers/misa_purchase_request_api.py
# -*- coding: utf-8 -*-
"""
API endpoint để sync Purchase Request từ MISA CRM theo mã
Tương tự như misa_po_api.py
"""
import logging
import json
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class MisaApiPurchaseRequest(http.Controller):

    @http.route('/api/misa/purchase_request/sync', type='json', auth='none', methods=['POST'], csrf=False)
    def api_misa_purchase_request_sync(self, **payload):
        """
        Public API: không yêu cầu login.
        Body JSON ví dụ:
        {
          "token": "hoanglongvu",
          "pr_code": "YCMH244197477416442",
          "create_when_missing": true
        }
        
        Trả về:
        {
          "ok": true/false,
          "res_id": 123,
          "name": "YCMH244197477416442",
          "action": "created" | "updated" | "not_found",
          "detail": "Chi tiết kết quả"
        }
        """

        # ---- Lấy JSON body an toàn ----
        try:
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
            pass

        # ---- Lấy token từ body hoặc header ----
        raw_token = (payload.get("token") if isinstance(payload, dict) else None) \
                    or request.httprequest.headers.get('X-MISA-Token')
        token = (raw_token or "").strip()

        _logger.info("MISA Purchase Request API /sync payload=%r token=%r", payload, token)

        # ---- Token check ----
        expected = request.env['ir.config_parameter'].sudo().get_param('misa.api.token') or "hoanglongvu"

        try:
            import re
            token = re.sub(r'[\u200B-\u200D\uFEFF]', '', token)
            expected = re.sub(r'[\u200B-\u200D\uFEFF]', '', expected)
        except Exception:
            pass

        if token != expected:
            return {"ok": False, "error": "invalid_token", "message": "Token không hợp lệ."}

        # ---- Lấy tham số nghiệp vụ ----
        pr_code = payload.get("pr_code")
        create_when_missing = payload.get("create_when_missing", True)

        if not pr_code:
            return {"ok": False, "error": "missing_pr_code", "message": "Thiếu mã yêu cầu mua hàng (pr_code)"}

        # ---- Chạy dưới quyền admin ----
        admin_user = request.env.ref("base.user_admin", raise_if_not_found=False)
        if not admin_user:
            return {"ok": False, "error": "admin_not_found"}

        try:
            env_admin = request.env(user=admin_user)
            
            result = env_admin["purchase.request"].api_sync_purchase_request_by_code(
                pr_code=pr_code,
                create_when_missing=bool(create_when_missing),
            )
            return result
        except Exception as e:
            _logger.exception("MISA Purchase Request API /sync exception: %s", e)
            return {"ok": False, "error": "exception", "message": str(e)}
