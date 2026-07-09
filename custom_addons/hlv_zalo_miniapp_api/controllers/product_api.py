# -*- coding: utf-8 -*-
import base64
import json
import logging
from datetime import timedelta, timezone

from odoo import fields, http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class ZaloProductAPI(http.Controller):
    """API Sản phẩm (product.product variant) cho Zalo Mini App"""

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
        if not rec_id:
            return None
        return f"/api/v1/zalo/image/{model}/{rec_id}/{field}"

    def _build_product_data(self, product):
        """Build standard product response dict from a product.product record."""
        # Get attribute values
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

        # Get category from template
        category = None
        if product.pos_categ_ids:
            cat = product.pos_categ_ids[0]
            category = {"id": cat.id, "name": cat.name}
        elif product.categ_id:
            category = {"id": product.categ_id.id, "name": product.categ_id.name}

        # Check promotional price from pricelist
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
    # GET /api/v1/zalo/products/list
    # =========================================================================
    @http.route(
        "/api/v1/zalo/products/list",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def product_list(self, **params):
        """Danh sách sản phẩm (variant) với sort/filter/query."""
        try:
            limit = self._parse_int(params.get("limit"), 20)
            offset = self._parse_int(params.get("offset"), 0)
            limit = min(max(limit, 1), 100)

            query = (params.get("query") or "").strip()
            sort = (params.get("sort") or "name").strip()
            category_id = self._parse_int(params.get("category_id"), 0)

            # Base domain
            domain = [
                ("x_active_zalo", "=", True),
                ("active", "=", True),
                ("sale_ok", "=", True),
            ]

            # Category filter
            if category_id:
                domain.append(("pos_categ_ids", "in", [category_id]))

            # Search query
            if query:
                domain.append(
                    "|",
                    ("display_name", "ilike", query),
                    "|",
                    ("default_code", "ilike", query),
                    ("barcode", "ilike", query),
                )

            # Sort mapping (dùng name thay vì display_name vì display_name ko stored)
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
    # GET /api/v1/zalo/products/<id>
    # =========================================================================
    @http.route(
        "/api/v1/zalo/products/<int:product_id>",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def product_detail(self, product_id, **params):
        """Chi tiết sản phẩm (variant)."""
        try:
            product = request.env["product.product"].sudo().browse(product_id)
            if not product.exists() or not product.active:
                return self._response_error("NOT_FOUND", "Sản phẩm không tồn tại", 404)

            if not product.x_active_zalo:
                return self._response_error("NOT_FOUND", "Sản phẩm không tồn tại", 404)

            data = self._build_product_data(product)

            # Add more details for detail view
            data["description_full"] = product.description or ""
            data["standard_price"] = product.standard_price  # cost price
            data["volume"] = product.volume or 0.0

            # Additional images
            images = []
            try:
                if hasattr(product.product_tmpl_id, "product_multi_images"):
                    for img in product.product_tmpl_id.product_multi_images:
                        if img.image_1920:
                            images.append(
                                self._get_image_url(
                                    "product.multi.image", img.id, "image_1920"
                                )
                            )
            except Exception:
                pass
            # Fallback: try template image
            if not images and product.product_tmpl_id.image_1920:
                images.append(
                    self._get_image_url(
                        "product.template", product.product_tmpl_id.id, "image_1920"
                    )
                )
            data["images"] = images

            return self._response_success(data)
        except Exception as e:
            _logger.exception("product_detail error")
            return self._response_error("SERVER_ERROR", str(e), 500)