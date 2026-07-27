# -*- coding: utf-8 -*-
import base64
import logging

from odoo import fields, http
from odoo.http import request, Response

from .base_api import ZaloBaseAPI

_logger = logging.getLogger(__name__)


class ZaloCategoryAPI(ZaloBaseAPI, http.Controller):
    """API Danh mục sản phẩm từ pos.category"""

    # =========================================================================
    # POST /api/v1/zalo/categories/list
    # =========================================================================
    @http.route(
        "/api/v1/zalo/categories/list",
        type="http",
        auth="public",
        methods=["POST", "OPTIONS"],
        csrf=False,
    )
    def category_list(self, **params):
        """Danh sách danh mục (pos.category) có phân trang."""
        if request.httprequest.method == "OPTIONS":
            return self._response_options()
        try:
            body = self._request_json()
            try:
                limit, offset = self._parse_limit_offset(body, default_limit=20, max_limit=100)
            except ValueError as e:
                return self._response_error("INVALID_INPUT", str(e))

            categories = request.env["pos.category"].sudo().search(
                [],
                limit=limit,
                offset=offset,
                order="sequence, name",
            )
            total = request.env["pos.category"].sudo().search_count([])

            data = []
            for cat in categories:
                img_url = None
                if hasattr(cat, "image_128") and cat.image_128:
                    img_url = self._get_image_url("pos.category", cat.id, "image_128")
                data.append({
                    "id": cat.id,
                    "x_misa_id": cat.x_misa_id if hasattr(cat, "x_misa_id") else None,
                    "name": cat.name,
                    "sequence": cat.sequence,
                    "parent_id": cat.parent_id.id if cat.parent_id else None,
                    "parent_name": cat.parent_id.name if cat.parent_id else None,
                    "image_url": img_url,
                })

            return self._response_success_cached({
                "total": total,
                "limit": limit,
                "offset": offset,
                "categories": data,
            }, max_age=300)
        except Exception as e:
            _logger.exception("category_list error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # =========================================================================
    # POST /api/v1/zalo/categories/products
    # =========================================================================
    @http.route(
        "/api/v1/zalo/categories/products",
        type="http",
        auth="public",
        methods=["POST", "OPTIONS"],
        csrf=False,
    )
    def category_products(self, **params):
        """Lấy sản phẩm (variant) theo danh mục.
        Body: {"category_id": 1, "limit": 10, "offset": 0}
        category_id có thể là x_misa_id hoặc ID nội bộ của Odoo."""
        if request.httprequest.method == "OPTIONS":
            return self._response_options()
        try:
            body = self._request_json()
            category_id = self._parse_int(body.get("category_id"), 0)
            try:
                limit, offset = self._parse_limit_offset(body, default_limit=20, max_limit=100)
            except ValueError as e:
                return self._response_error("INVALID_INPUT", str(e))

            if not category_id:
                return self._response_error("INVALID_INPUT", "Thiếu category_id")

            # Tìm category: ưu tiên x_misa_id, fallback internal ID
            category = request.env["pos.category"].sudo().search(
                [("x_misa_id", "=", category_id)], limit=1
            )
            if not category:
                category = request.env["pos.category"].sudo().browse(category_id)
            if not category.exists():
                return self._response_error("NOT_FOUND", "Danh mục không tồn tại", 404)

            domain = [
                ("x_zalo_categ_ids", "in", [category.id]),
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
                "category_id": category.id,
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
    # POST /api/v1/zalo/image
    # Body: {"model": "product.product", "id": 23812, "field": "image_128"}
    # =========================================================================
    @http.route(
        "/api/v1/zalo/image/<string:safe_model>/<int:rec_id>/<string:field>",
        type="http",
        auth="public",
        methods=["GET", "OPTIONS"],
        csrf=False,
    )
    def get_image_by_path(self, safe_model, rec_id, field="image_128", **params):
        """Trả ảnh dạng binary qua GET với path params.
        URL: /api/v1/zalo/image/product-product/123/image_128
        Model name dùng dấu - thay cho . (vd: product-product = product.product)"""
        if request.httprequest.method == "OPTIONS":
            return self._response_options()
        try:
            safe_model = (safe_model or "").strip()
            if not safe_model:
                return self._response_error("INVALID_INPUT", "Thiếu model", 400)
            # Convert safe model name back to dot notation
            model = safe_model.replace("-", ".")
            if not model or not rec_id:
                return self._response_error("INVALID_INPUT", "Thiếu model hoặc id", 400)
            # Whitelist model check
            if model not in self.ALLOWED_IMAGE_MODELS:
                _logger.warning("Rejected image access for unauthorized model: %s", model)
                return self._response_error("FORBIDDEN", "Model không được phép", 403)

            Model = request.env.get(model)
            if Model is None:
                return self._response_error("NOT_FOUND", "Model không tồn tại", 404)

            record = Model.sudo().browse(rec_id)
            if not record.exists():
                return self._response_error("NOT_FOUND", "Bản ghi không tồn tại", 404)

            image_data = record[field] if hasattr(record, field) else None
            if not image_data:
                return self._response_error("NOT_FOUND", "Không có ảnh", 404)

            return Response(
                base64.b64decode(image_data),
                content_type="image/png",
            )
        except Exception as e:
            _logger.exception("get_image_by_path error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    @http.route(
        "/api/v1/zalo/image",
        type="http",
        auth="public",
        methods=["POST", "OPTIONS"],
        csrf=False,
    )
    def get_image(self, **params):
        """Trả ảnh dạng binary qua POST với JSON body.
        Security: Chỉ cho phép các model trong ALLOWED_IMAGE_MODELS.
        Body: {"model": "product.product", "id": 23812, "field": "image_128"}"""
        if request.httprequest.method == "OPTIONS":
            return self._response_options()
        try:
            body = self._request_json()
            model = (body.get("model") or "").strip()
            rec_id = self._parse_int(body.get("id"), 0)
            field = (body.get("field") or "image_128").strip()
            if not model or not rec_id:
                return self._response_error("INVALID_INPUT", "Thiếu model hoặc id")
            # Whitelist model check
            if model not in self.ALLOWED_IMAGE_MODELS:
                _logger.warning("Rejected image access for unauthorized model: %s", model)
                return self._response_error("FORBIDDEN", "Model không được phép", 403)

            Model = request.env.get(model)
            if Model is None:
                return self._response_error("NOT_FOUND", "Model không tồn tại", 404)

            record = Model.sudo().browse(rec_id)
            if not record.exists():
                return self._response_error("NOT_FOUND", "Bản ghi không tồn tại", 404)

            image_data = record[field] if hasattr(record, field) else None
            if not image_data:
                return self._response_error("NOT_FOUND", "Không có ảnh", 404)

            return Response(
                base64.b64decode(image_data),
                content_type="image/png",
            )
        except Exception as e:
            _logger.exception("get_image error")
            return self._response_error("SERVER_ERROR", str(e), 500)
