# -*- coding: utf-8 -*-
import logging

from odoo import http
from odoo.http import request, Response

from .base_api import ZaloBaseAPI

_logger = logging.getLogger(__name__)


class ZaloCartAPI(ZaloBaseAPI, http.Controller):
    """API Giỏ hàng cho Zalo Mini App — lưu thông tin vào zalo.miniapp.cart.line (Không tạo sale.order draft)"""

    def _cart_to_dict(self, contact_id):
        CartLine = request.env["zalo.miniapp.cart.line"].sudo()
        cart_lines = CartLine.search([("partner_id", "=", contact_id)], order="id desc")

        lines = []
        for line in cart_lines:
            if line.product_id and line.product_id.exists() and line.product_id.x_active_zalo:
                price = line.product_id.x_zalo_price or line.product_id.list_price or 0.0
                lines.append({
                    "id": line.id,
                    "product_id": line.product_id.id,
                    "product_name": line.product_id.display_name,
                    "product_code": line.product_id.default_code or "",
                    "quantity": line.quantity,
                    "price_unit": price,
                    "x_zalo_price": price,
                    "subtotal": price * line.quantity,
                    "image_url": f"/api/v1/zalo/image/product.product/{line.product_id.id}/image_128" if line.product_id.image_128 else None,
                })

        return {
            "partner_id": contact_id,
            "lines": lines,
            "total": sum(l["subtotal"] for l in lines),
            "line_count": len(lines),
        }

    # POST /api/v1/zalo/cart/get
    @http.route("/api/v1/zalo/cart/get", type="http", auth="public", methods=["POST", "OPTIONS"], csrf=False)
    def cart_get(self, **params):
        """Body: {"contact_id": 1}"""
        if request.httprequest.method == "OPTIONS":
            return self._response_options()
        try:
            body = self._request_json()
            contact_id = self._parse_int(body.get("contact_id"), 0)
            if not contact_id:
                return self._response_error("INVALID_INPUT", "Thiếu contact_id")

            # Auth + ownership check
            auth_result = self._auth_and_verify_owner(contact_id)
            if isinstance(auth_result, Response):
                return auth_result

            return self._response_success(self._cart_to_dict(contact_id))
        except Exception as e:
            _logger.exception("cart_get error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # POST /api/v1/zalo/cart/add
    @http.route("/api/v1/zalo/cart/add", type="http", auth="public", methods=["POST", "OPTIONS"], csrf=False)
    def cart_add(self, **params):
        """Body: {"contact_id": 1, "product_id": 42, "quantity": 2}"""
        if request.httprequest.method == "OPTIONS":
            return self._response_options()
        try:
            body = self._request_json()
            contact_id = self._parse_int(body.get("contact_id"))
            product_id = self._parse_int(body.get("product_id"))
            quantity = self._parse_float(body.get("quantity"), 1.0)

            if not contact_id or not product_id:
                return self._response_error("INVALID_INPUT", "Thiếu contact_id hoặc product_id")
            if quantity <= 0:
                return self._response_error("INVALID_INPUT", "Số lượng phải > 0")

            # Auth + ownership check
            auth_result = self._auth_and_verify_owner(contact_id)
            if isinstance(auth_result, Response):
                return auth_result

            Product = request.env["product.product"].sudo()
            product = Product.browse(product_id)
            if not product.exists() or not product.active or not product.x_active_zalo:
                return self._response_error("NOT_FOUND", "Sản phẩm không tồn tại", 404)

            if product.free_qty <= 0:
                return self._response_error("OUT_OF_STOCK", f"Sản phẩm '{product.display_name}' hiện đang tạm hết hàng. Vui lòng liên hệ Zalo OA để nhận tư vấn & báo giá.", 400)

            CartLine = request.env["zalo.miniapp.cart.line"].sudo()
            existing_line = CartLine.search([
                ("partner_id", "=", contact_id),
                ("product_id", "=", product_id),
            ], limit=1)

            if existing_line:
                existing_line.write({"quantity": existing_line.quantity + quantity})
            else:
                CartLine.create({
                    "partner_id": contact_id,
                    "product_id": product_id,
                    "quantity": quantity,
                })

            return self._response_success(self._cart_to_dict(contact_id))
        except Exception as e:
            _logger.exception("cart_add error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # PUT /api/v1/zalo/cart/update
    @http.route("/api/v1/zalo/cart/update", type="http", auth="public", methods=["PUT", "OPTIONS"], csrf=False)
    def cart_update(self, **params):
        """Body: {"contact_id": 1, "line_id": 12, "quantity": 3}"""
        if request.httprequest.method == "OPTIONS":
            return self._response_options()
        try:
            body = self._request_json()
            contact_id = self._parse_int(body.get("contact_id"))
            line_id = self._parse_int(body.get("line_id"))
            quantity = self._parse_float(body.get("quantity"), 0)

            if not contact_id or not line_id:
                return self._response_error("INVALID_INPUT", "Thiếu contact_id hoặc line_id")

            # Auth + ownership check
            auth_result = self._auth_and_verify_owner(contact_id)
            if isinstance(auth_result, Response):
                return auth_result

            CartLine = request.env["zalo.miniapp.cart.line"].sudo()
            line = CartLine.browse(line_id)
            if not line.exists() or line.partner_id.id != contact_id:
                return self._response_error("NOT_FOUND", "Dòng sản phẩm không tồn tại", 404)

            if quantity <= 0:
                line.unlink()
            else:
                line.write({"quantity": quantity})

            return self._response_success(self._cart_to_dict(contact_id))
        except Exception as e:
            _logger.exception("cart_update error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # POST /api/v1/zalo/cart/remove
    @http.route("/api/v1/zalo/cart/remove", type="http", auth="public", methods=["POST", "OPTIONS"], csrf=False)
    def cart_remove(self, **params):
        """Body: {"contact_id": 1, "line_id": 12}"""
        if request.httprequest.method == "OPTIONS":
            return self._response_options()
        try:
            body = self._request_json()
            contact_id = self._parse_int(body.get("contact_id"))
            line_id = self._parse_int(body.get("line_id"))

            if not contact_id or not line_id:
                return self._response_error("INVALID_INPUT", "Thiếu contact_id hoặc line_id")

            # Auth + ownership check
            auth_result = self._auth_and_verify_owner(contact_id)
            if isinstance(auth_result, Response):
                return auth_result

            CartLine = request.env["zalo.miniapp.cart.line"].sudo()
            line = CartLine.browse(line_id)
            if line.exists() and line.partner_id.id == contact_id:
                line.unlink()

            return self._response_success(self._cart_to_dict(contact_id))
        except Exception as e:
            _logger.exception("cart_remove error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # POST /api/v1/zalo/cart/clear
    @http.route("/api/v1/zalo/cart/clear", type="http", auth="public", methods=["POST", "OPTIONS"], csrf=False)
    def cart_clear(self, **params):
        """Body: {"contact_id": 1}"""
        if request.httprequest.method == "OPTIONS":
            return self._response_options()
        try:
            body = self._request_json()
            contact_id = self._parse_int(body.get("contact_id"), 0)
            if not contact_id:
                return self._response_error("INVALID_INPUT", "Thiếu contact_id")

            # Auth + ownership check
            auth_result = self._auth_and_verify_owner(contact_id)
            if isinstance(auth_result, Response):
                return auth_result

            CartLine = request.env["zalo.miniapp.cart.line"].sudo()
            cart_lines = CartLine.search([("partner_id", "=", contact_id)])
            cart_lines.unlink()

            return self._response_success({"message": "Đã xóa giỏ hàng"})
        except Exception as e:
            _logger.exception("cart_clear error")
            return self._response_error("SERVER_ERROR", str(e), 500)