# -*- coding: utf-8 -*-
import logging

from odoo import http
from odoo.http import request

from .base_api import ZaloBaseAPI

_logger = logging.getLogger(__name__)


class ZaloConfigAPI(ZaloBaseAPI, http.Controller):
    """API Cấu hình ứng dụng Zalo Mini App"""

    @http.route(
        "/api/v1/zalo/config",
        type="http",
        auth="public",
        methods=["POST", "GET", "OPTIONS"],
        csrf=False,
    )
    def get_config(self, **params):
        """Lấy cấu hình ứng dụng Zalo Mini App (Zalo OA ID, Tên, Mô tả ngắn)."""
        if request.httprequest.method == "OPTIONS":
            return self._response_options()
        try:
            get_param = request.env["ir.config_parameter"].sudo().get_param
            oa_id = get_param("hlv_zalo_miniapp.oa_id", "3668388836585145887")
            oa_name = get_param("hlv_zalo_miniapp.oa_name", "Hoàng Long Vũ")
            oa_subtext = get_param(
                "hlv_zalo_miniapp.oa_subtext",
                "Theo dõi OA để nhận thông tin khuyến mãi, bảo hành và ưu đãi mới nhất!"
            )

            return self._response_success_cached({
                "oa_id": oa_id,
                "oa_name": oa_name,
                "oa_subtext": oa_subtext,
            }, max_age=300)
        except Exception as e:
            _logger.exception("get_config error")
            return self._response_error("SERVER_ERROR", str(e), 500)
