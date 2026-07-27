# -*- coding: utf-8 -*-
import json
import logging

from odoo import http
from odoo.http import request

from .base_api import ZaloBaseAPI

_logger = logging.getLogger(__name__)


class ZaloMiniAppBannerAPI(ZaloBaseAPI, http.Controller):

    @http.route("/api/v1/zalo/banners/list", type="http", auth="public", methods=["POST", "OPTIONS"], csrf=False)
    def list_banners(self, **kwargs):
        """
        POST /api/v1/zalo/banners/list
        """
        if request.httprequest.method == "OPTIONS":
            return self._response_options()
        try:
            body = self._request_json()
            try:
                limit, offset = self._parse_limit_offset(body, default_limit=10, max_limit=100)
            except ValueError as e:
                return self._response_error("INVALID_INPUT", str(e))

            domain = [("active", "=", True)]

            banner_model = request.env["zalo.miniapp.banner"].sudo()
            banners = banner_model.search(domain, order="sequence asc, id asc", limit=limit, offset=offset)
            total = banner_model.search_count(domain)

            data = []
            for b in banners:
                data.append({
                    "id": b.id,
                    "name": b.name,
                    "link": b.link or "",
                    "image_url": self._get_image_url("zalo.miniapp.banner", b.id, "image"),
                })

            return self._response_success_cached({
                "banners": data,
                "total": total,
                "limit": limit,
                "offset": offset,
            }, max_age=300)
        except Exception as e:
            _logger.exception("list_banners error")
            return self._response_error("SERVER_ERROR", str(e), 500)