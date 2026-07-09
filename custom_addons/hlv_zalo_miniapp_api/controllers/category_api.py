# -*- coding: utf-8 -*-
import json
import logging
import re
from datetime import timedelta, timezone

from odoo import fields, http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class ZaloCategoryAPI(http.Controller):
    """API Danh mục sản phẩm từ pos.category"""

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _response_success(data=None, status=200):
        payload = {"success": True, "data": data or {}}
        return Response(
            json.dumps(payload, default=str),
            status=status,
            content_type="application/json",
        )

    @staticmethod
    def _response_error(code, message, status=400):
        payload = {
            "success": False,
            "error": {"code": code, "message": message},
        }
        return Response(
            json.dumps(payload, default=str),
            status=status,
            content_type="application/json",
        )

    @staticmethod
    def _parse_int(value, default=0):
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _get_image_url(model, rec_id, field="image_128"):
        """Return a relative URL for the image."""
        if not rec_id:
            return None
        return f"/api/v1/zalo/image/{model}/{rec_id}/{field}"

    # =========================================================================
    # GET /api/v1/zalo/categories/list
    # =========================================================================
    @http.route(
        "/api/v1/zalo/categories/list",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def category_list(self, **params):
        """Danh sách danh mục (pos.category) có phân trang."""
        try:
            limit = self._parse_int(params.get("limit"), 20)
            offset = self._parse_int(params.get("offset"), 0)
            limit = min(max(limit, 1), 100)

            categories = request.env["pos.category"].sudo().search(
                [("available_in_pos", "=", True)],
                limit=limit,
                offset=offset,
                order="sequence, name",
            )
            total = request.env["pos.category"].sudo().search_count(
                [("available_in_pos", "=", True)]
            )

            data = []
            for cat in categories:
                img_url = None
                if hasattr(cat, "image_128") and cat.image_128:
                    img_url = self._get_image_url("pos.category", cat.id, "image_128")
                data.append({
                    "id": cat.id,
                    "name": cat.name,
                    "sequence": cat.sequence,
                    "parent_id": cat.parent_id.id if cat.parent_id else None,
                    "parent_name": cat.parent_id.name if cat.parent_id else None,
                    "image_url": img_url,
                })

            return self._response_success({
                "total": total,
                "limit": limit,
                "offset": offset,
                "categories": data,
            })
        except Exception as e:
            _logger.exception("category_list error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # =========================================================================
    # GET /api/v1/zalo/categories/<id>/products
    # =========================================================================
    @http.route(
        "/api/v1/zalo/categories/<int:category_id>/products",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def category_products(self, category_id, **params):
        """Lấy sản phẩm (variant) theo danh mục."""
        try:
            limit = self._parse_int(params.get("limit"), 20)
            offset = self._parse_int(params.get("offset"), 0)
            limit = min(max(limit, 1), 100)

            category = request.env["pos.category"].sudo().browse(category_id)
            if not category.exists():
                return self._response_error("NOT_FOUND", "Danh mục không tồn tại", 404)

            domain = [
                ("pos_categ_ids", "in", [category_id]),
                ("x_active_zalo", "=", True),
                ("active", "=", True),
                ("sale_ok", "=", True),
            ]

            products = request.env["product.product"].sudo().search(
                domain, limit=limit, offset=offset, order="name"
            )
            total = request.env["product.product"].sudo().search_count(domain)

            data = []
            for p in products:
                img_url = None
                if p.image_128:
                    img_url = self._get_image_url("product.product", p.id, "image_128")
                data.append({
                    "id": p.id,
                    "template_id": p.product_tmpl_id.id,
                    "name": p.display_name,
                    "default_code": p.default_code,
                    "barcode": p.barcode,
                    "x_zalo_price": p.x_zalo_price or 0.0,
                    "list_price": p.list_price,
                    "free_qty": p.free_qty or 0.0,
                    "uom": p.uom_id.name if p.uom_id else "",
                    "image_url": img_url,
                })

            return self._response_success({
                "category_id": category_id,
                "category_name": category.name,
                "total": total,
                "limit": limit,
                "offset": offset,
                "products": data,
            })
        except Exception as e:
            _logger.exception("category_products error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # =========================================================================
    # GET /api/v1/zalo/image/<model>/<id>/<field>
    # =========================================================================
    @http.route(
        "/api/v1/zalo/image/<model>/<int:rec_id>/<field>",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def get_image(self, model, rec_id, field="image_128"):
        """Trả ảnh dạng binary."""
        try:
            Model = request.env.get(model)
            if not Model:
                return self._response_error("NOT_FOUND", "Model không tồn tại", 404)

            record = Model.sudo().browse(rec_id)
            if not record.exists():
                return self._response_error("NOT_FOUND", "Bản ghi không tồn tại", 404)

            image_data = record[field] if hasattr(record, field) else None
            if not image_data:
                return self._response_error("NOT_FOUND", "Không có ảnh", 404)

            import base64
            return Response(
                base64.b64decode(image_data),
                content_type="image/png",
            )
        except Exception as e:
            _logger.exception("get_image error")
            return self._response_error("SERVER_ERROR", str(e), 500)