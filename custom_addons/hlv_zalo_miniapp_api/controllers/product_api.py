# -*- coding: utf-8 -*-
import base64
import logging
from datetime import timedelta, timezone

from odoo import fields, http
from odoo.http import request

from .base_api import ZaloBaseAPI

_logger = logging.getLogger(__name__)


class ZaloProductAPI(ZaloBaseAPI, http.Controller):
    """API Sản phẩm (product.product variant) cho Zalo Mini App"""

    def _build_product_data(self, product):
        """Build standard product response dict from a product.product record."""
        attributes = []
        if hasattr(product, "product_template_attribute_value_ids"):
            for ptav in product.product_template_attribute_value_ids:
                attr = ptav.attribute_id
                val = ptav.product_attribute_value_id
                attributes.append({
                    "id": val.id,
                    "name": attr.name,
                    "value": val.name,
                })

        category = None
        if product.pos_categ_ids:
            cat = product.pos_categ_ids[0]
            category = {"id": cat.id, "name": cat.name}
        elif product.categ_id:
            category = {"id": product.categ_id.id, "name": product.categ_id.name}

        promotional_price = None
        try:
            pricelist = request.env["product.pricelist"].sudo().search([
                ("active", "=", True),
            ], limit=1, order="id")
            if pricelist:
                promo = pricelist._get_product_price(product, quantity=1.0)
                if promo and promo != product.x_zalo_price:
                    promotional_price = promo
        except Exception:
            pass

        img_url = None
        if product.image_128:
            img_url = self._get_image_url("product.product", product.id, "image_128")

        return {
            "id": product.id,
            "template_id": product.product_tmpl_id.id,
            "name": product.display_name,
            "template_name": product.product_tmpl_id.name,
            "default_code": product.default_code,
            "barcode": product.barcode,
            "x_zalo_price": product.x_zalo_price or 0.0,
            "list_price": product.list_price,
            "promotional_price": promotional_price,
            "free_qty": product.free_qty or 0.0,
            "uom": product.uom_id.name if product.uom_id else "",
            "weight": product.weight or 0.0,
            "category": category,
            "attributes": attributes,
            "image_url": img_url,
            "description": product.description_sale or "",
            "description_html": product.description or "",
        }

    # =========================================================================
    # POST /api/v1/zalo/products/list
    # =========================================================================
    @http.route(
        "/api/v1/zalo/products/list",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def product_list(self, **params):
        """Danh sách sản phẩm (variant) với sort/filter/query.
        Body: {"limit":10, "offset":0, "query":"áo", "sort":"name", "category_id":0}"""
        try:
            body = self._request_json()
            limit = self._parse_int(body.get("limit"), 20)
            offset = self._parse_int(body.get("offset"), 0)
            limit = min(max(limit, 1), 100)

            query = (body.get("query") or "").strip()
            sort = (body.get("sort") or "name").strip()
            category_id = self._parse_int(body.get("category_id"), 0)

            domain = [
                ("x_active_zalo", "=", True),
                ("active", "=", True),
                ("sale_ok", "=", True),
            ]

            if category_id:
                domain.append(("pos_categ_ids", "in", [category_id]))

            if query:
                domain += [
                    "|",
                    ("name", "ilike", query),
                    "|",
                    ("default_code", "ilike", query),
                    ("barcode", "ilike", query),
                ]

            sort_map = {
                "name": "name",
                "-name": "name desc",
                "x_zalo_price": "x_zalo_price",
                "-x_zalo_price": "x_zalo_price desc",
                "create_date": "create_date",
                "-create_date": "create_date desc",
                "list_price": "list_price",
                "-list_price": "list_price desc",
            }
            order = sort_map.get(sort, "name")

            products = request.env["product.product"].sudo().search(
                domain, limit=limit, offset=offset, order=order
            )
            total = request.env["product.product"].sudo().search_count(domain)

            data = [self._build_product_data(p) for p in products]

            return self._response_success({
                "total": total,
                "limit": limit,
                "offset": offset,
                "products": data,
            })
        except Exception as e:
            _logger.exception("product_list error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # =========================================================================
    # POST /api/v1/zalo/products/detail
    # =========================================================================
    @http.route(
        "/api/v1/zalo/products/detail",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def product_detail(self, **params):
        """Chi tiết sản phẩm (variant).
        Body: {"product_id": 1}"""
        try:
            body = self._request_json()
            product_id = self._parse_int(body.get("product_id"), 0)
            if not product_id:
                return self._response_error("INVALID_INPUT", "Thiếu product_id")

            product = request.env["product.product"].sudo().browse(product_id)
            if not product.exists() or not product.active:
                return self._response_error("NOT_FOUND", "Sản phẩm không tồn tại", 404)

            if not product.x_active_zalo:
                return self._response_error("NOT_FOUND", "Sản phẩm không tồn tại", 404)

            data = self._build_product_data(product)

            data["description_full"] = product.description or ""
            data["standard_price"] = product.standard_price
            data["volume"] = product.volume or 0.0

            images = []
            try:
                if hasattr(product.product_tmpl_id, "product_multi_images"):
                    for img in product.product_tmpl_id.product_multi_images:
                        if img.image_1920:
                            images.append(
                                self._get_image_url("product.multi.image", img.id, "image_1920")
                            )
            except Exception:
                pass
            if not images and product.product_tmpl_id.image_1920:
                images.append(
                    self._get_image_url("product.template", product.product_tmpl_id.id, "image_1920")
                )
            data["images"] = images

            return self._response_success(data)
        except Exception as e:
            _logger.exception("product_detail error")
            return self._response_error("SERVER_ERROR", str(e), 500)