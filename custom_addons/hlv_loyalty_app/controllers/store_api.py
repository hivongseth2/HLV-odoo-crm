# -*- coding: utf-8 -*-
import base64
import json
import logging
from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class LoyaltyAppStoreAPI(http.Controller):

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

    @http.route("/api/v1/loyalty/stores", type="http", auth="public", methods=["GET", "POST", "OPTIONS"], csrf=False, cors="*")
    def list_stores(self, **kwargs):
        """
        GET /api/v1/loyalty/stores
        Lấy danh sách chi nhánh / cửa hàng cho Loyalty Mobile App.
        """
        if request.httprequest.method == "OPTIONS":
            return Response(status=200, headers=self._cors_headers())

        try:
            store_model = request.env["hlv.loyalty.store"].sudo()
            stores = store_model.get_active_stores_data()

            return self._json_response({
                "success": True,
                "data": {
                    "stores": stores,
                    "total": len(stores),
                },
                "stores": stores,
            })
        except Exception as e:
            _logger.exception("list_stores error: %s", e)
            return self._json_response({"success": False, "error": str(e)}, status=500)

    @http.route("/api/v1/loyalty/store/<int:store_id>/image", type="http", auth="public", methods=["GET", "OPTIONS"], csrf=False, cors="*")
    def get_store_image(self, store_id, **kwargs):
        """
        GET /api/v1/loyalty/store/<id>/image
        Trả về file ảnh nhị phân của cửa hàng / chi nhánh.
        """
        if request.httprequest.method == "OPTIONS":
            return Response(status=200, headers=self._cors_headers())

        store = request.env["hlv.loyalty.store"].sudo().browse(store_id)
        if not store.exists() or not store.image:
            return Response(status=404, headers=self._cors_headers())

        try:
            image_data = base64.b64decode(store.image)
            headers = self._cors_headers() + [
                ("Content-Type", "image/png"),
                ("Content-Length", str(len(image_data))),
                ("Cache-Control", "public, max-age=86400"),
            ]
            return Response(image_data, status=200, headers=headers)
        except Exception as e:
            _logger.exception("get_store_image error: %s", e)
            return Response(status=500, headers=self._cors_headers())

