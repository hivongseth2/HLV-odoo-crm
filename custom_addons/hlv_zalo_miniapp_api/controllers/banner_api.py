# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import json

class ZaloMiniAppBannerAPI(http.Controller):
    
    def _response_success(self, data=None):
        res = {"success": True}
        if data is not None:
            res["data"] = data
        return request.make_response(
            json.dumps(res, default=str),
            headers=[("Content-Type", "application/json")]
        )

    def _response_error(self, code, message, status=400):
        res = {
            "success": False,
            "error": {
                "code": code,
                "message": message
            }
        }
        return request.make_response(
            json.dumps(res, default=str),
            headers=[("Content-Type", "application/json")],
            status=status
        )

    @http.route("/api/v1/zalo/banners/list", type="http", auth="public", methods=["POST"], csrf=False)
    def list_banners(self, **kwargs):
        """
        POST /api/v1/zalo/banners/list
        """
        try:
            if request.httprequest.data:
                payload = json.loads(request.httprequest.data.decode("utf-8"))
            else:
                payload = {}
        except Exception:
            payload = {}

        limit = max(1, min(int(payload.get("limit", 10)), 100))
        offset = max(0, int(payload.get("offset", 0)))

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
                "image_url": f"/api/v1/zalo/image/zalo.miniapp.banner/{b.id}/image",
            })

        return self._response_success({
            "banners": data,
            "total": total,
            "limit": limit,
            "offset": offset
        })
