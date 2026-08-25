# -*- coding: utf-8 -*-
import base64
import json
import logging
from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class LoyaltyAppBannerAPI(http.Controller):

    def _cors_headers(self):
        return [
            ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
            ("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With"),
            ("Access-Control-Max-Age", "86400"),
        ]

    def _json_response(self, data, status=200):
        return Response(
            json.dumps(data, ensure_ascii=False),
            status=status,
            content_type="application/json; charset=utf-8",
            headers=self._cors_headers(),
        )

    @http.route("/api/v1/loyalty/banners", type="http", auth="public", methods=["GET", "POST", "OPTIONS"], csrf=False, cors="*")
    def list_banners(self, **kwargs):
        """
        GET /api/v1/loyalty/banners
        Lấy danh sách banner ưu đãi cho Loyalty Mobile App.
        """
        if request.httprequest.method == "OPTIONS":
            return Response(status=200, headers=self._cors_headers())

        try:
            limit = int(kwargs.get("limit", 10))
            banner_model = request.env["hlv.loyalty.banner"].sudo()
            banners = banner_model.get_active_banners_data(limit=limit)

            return self._json_response({
                "success": True,
                "data": {
                    "banners": banners,
                    "total": len(banners),
                },
                "banners": banners,
            })
        except Exception as e:
            _logger.exception("list_banners error: %s", e)
            return self._json_response({"success": False, "error": str(e)}, status=500)

    @http.route("/api/v1/loyalty/banner/<int:banner_id>/image", type="http", auth="public", methods=["GET", "OPTIONS"], csrf=False, cors="*")
    def get_banner_image(self, banner_id, **kwargs):
        """
        GET /api/v1/loyalty/banner/<id>/image
        Trả về file ảnh nhị phân của banner.
        """
        if request.httprequest.method == "OPTIONS":
            return Response(status=200, headers=self._cors_headers())

        banner = request.env["hlv.loyalty.banner"].sudo().browse(banner_id)
        if not banner.exists() or not banner.image:
            return Response(status=404, headers=self._cors_headers())

        try:
            image_data = base64.b64decode(banner.image)
            headers = self._cors_headers() + [
                ("Content-Type", "image/png"),
                ("Content-Length", str(len(image_data))),
                ("Cache-Control", "public, max-age=86400"),
            ]
            return Response(image_data, status=200, headers=headers)
        except Exception as e:
            _logger.exception("get_banner_image error: %s", e)
            return Response(status=500, headers=self._cors_headers())

