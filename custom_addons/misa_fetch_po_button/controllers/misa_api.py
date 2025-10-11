# controllers/misa_api.py
# -*- coding: utf-8 -*-
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

class MisaApiSaleOrder(http.Controller):

    @http.route('/api/misa/sale_order/resync', type='json', auth='none', methods=['POST'], csrf=False)
    def api_misa_sale_order_resync(self, **payload):
        # Lấy từ body JSON hoặc header
        raw_token = payload.get("token") or request.httprequest.headers.get('X-MISA-Token')
        token = (raw_token or "").strip()

        _logger.info("MISA API payload=%r token=%r headers_token=%r jsonrequest=%r",
                     payload, token, request.httprequest.headers.get('X-MISA-Token'),
                     request.jsonrequest)

        # (khuyến nghị) lấy token từ system parameter, fallback literal
        expected = request.env['ir.config_parameter'].sudo().get_param('misa.api.token') or "hoanglongvu"

        # Loại ký tự vô hình (zero-width) nếu có
        try:
            import re
            token_clean = re.sub(r'[\u200B-\u200D\uFEFF]', '', token)
            expected_clean = re.sub(r'[\u200B-\u200D\uFEFF]', '', expected)
        except Exception:
            token_clean = token
            expected_clean = expected

        if token_clean != expected_clean:
            return {"ok": False, "error": "invalid_token", "message": "Token không hợp lệ."}

        admin_user = request.env.ref("base.user_admin", raise_if_not_found=False)
        if not admin_user:
            return {"ok": False, "error": "admin_not_found"}

        misa_order_id = payload.get("misa_order_id")
        warehouse_id = payload.get("warehouse_id")
        create_when_missing = payload.get("create_when_missing", True)

        try:
            env_admin = request.env(user=admin_user).sudo()
            result = env_admin["sale.order"].api_resync_by_misa(
                misa_order_id=misa_order_id,
                warehouse_id=warehouse_id,
                create_when_missing=bool(create_when_missing),
            )
            return result
        except Exception as e:
            return {"ok": False, "error": "exception", "message": str(e)}
