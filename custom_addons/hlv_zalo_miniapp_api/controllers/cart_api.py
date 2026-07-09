# -*- coding: utf-8 -*-
import json
import logging

from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class ZaloCartAPI(http.Controller):
    """API Giỏ hàng cho Zalo Mini App — dùng sale.order draft"""

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
    def _parse_float(value, default=0.0):
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _request_json():
        raw = request.httprequest.data or b"{}"
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            return {}

    def _get_or_create_cart(self, contact_id):
        """Get existing draft SO for this partner, or create new one."""
        Partner = request.env["res.partner"].sudo()
        SaleOrder = request.env["sale.order"].sudo()

        partner = Partner.browse(contact_id)
        if not partner.exists():
            return None, "Khách hàng không tồn tại"

        # Find existing draft cart for this partner
        cart = SaleOrder.search([
            ("partner_id", "=", contact_id),
            ("state", "=", "draft"),
            ("team_id", "=", False),  # No sales team = cart
        ], limit=1, order="id desc")

        if not cart:
            # Create new cart
            cart = SaleOrder.create({
                "partner_id": contact_id,
                "partner_invoice_id": contact_id,
                "partner_shipping_id": contact_id,
                "state": "draft",
            })

        return cart, None

    def _cart_to_dict(self, cart):
        """Convert cart SO to dict for API response."""
        lines = []
        for line in cart.order_line:
            if line.product_id and line.product_id.x_active_zalo:
                lines.append({
                    "id": line.id,
                    "product_id": line.product_id.id,
                    "product_name": line.product_id.display_name,
                    "product_code": line.product_id.default_code,
                    "quantity": line.product_uom_qty,
                    "price_unit": line.price_unit,
                    "x_zalo_price": line.product_id.x_zalo_price or 0.0,
                    "subtotal": line.price_subtotal,
                    "image_url": (
                        f"/api/v1/zalo/image/product.product/{line.product_id.id}/image_128"
                        if line.product_id.image_128 else None
                    ),
                })

        return {
            "id": cart.id,
            "partner_id": cart.partner_id.id,
            "partner_name": cart.partner_id.name,
            "state": cart.state,
            "lines": lines,
            "total": sum(l.price_subtotal for l in cart.order_line),
            "line_count": len(lines),
            "create_date": cart.create_date,
        }

    # =========================================================================
    # GET /api/v1/zalo/cart/<contact_id>
    # =========================================================================
    @http.route(
        "/api/v1/zalo/cart/<int:contact_id>",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def cart_get(self, contact_id, **params):
        """Lấy giỏ hàng hiện tại của contact."""
        try:
            cart, error = self._get_or_create_cart(contact_id)
            if error:
                return self._response_error("NOT_FOUND", error, 404)
            return self._response_success(self._cart_to_dict(cart))
        except Exception as e:
            _logger.exception("cart_get error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # =========================================================================
    # POST /api/v1/zalo/cart/add
    # =========================================================================
    @http.route(
        "/api/v1/zalo/cart/add",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def cart_add(self, **params):
        """
        Thêm sản phẩm vào giỏ.
        Body: {"contact_id": 1, "product_id": 42, "quantity": 2}
        """
        try:
            body = self._request_json()
            contact_id = self._parse_int(body.get("contact_id"))
            product_id = self._parse_int(body.get("product_id"))
            quantity = self._parse_float(body.get("quantity"), 1.0)

            if not contact_id or not product_id:
                return self._response_error("INVALID_INPUT", "Thiếu contact_id hoặc product_id")
            if quantity <= 0:
                return self._response_error("INVALID_INPUT", "Số lượng phải > 0")

            Product = request.env["product.product"].sudo()
            product = Product.browse(product_id)

            if not product.exists() or not product.active:
                return self._response_error("NOT_FOUND", "Sản phẩm không tồn tại", 404)
            if not product.x_active_zalo:
                return self._response_error("NOT_FOUND", "Sản phẩm không tồn tại", 404)

            cart, error = self._get_or_create_cart(contact_id)
            if error:
                return self._response_error("NOT_FOUND", error, 404)

            # Check if product already in cart
            existing_line = cart.order_line.filtered(
                lambda l: l.product_id.id == product_id
            )
            if existing_line:
                # Update quantity
                existing_line[0].write({
                    "product_uom_qty": existing_line[0].product_uom_qty + quantity,
                })
            else:
                # Add new line
                price = product.x_zalo_price or product.list_price
                SaleOrderLine = request.env["sale.order.line"].sudo()
                SaleOrderLine.create({
                    "order_id": cart.id,
                    "product_id": product_id,
                    "product_uom_qty": quantity,
                    "price_unit": price,
                    "name": product.display_name,
                })

            return self._response_success(self._cart_to_dict(cart))
        except Exception as e:
            _logger.exception("cart_add error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # =========================================================================
    # PUT /api/v1/zalo/cart/update
    # =========================================================================
    @http.route(
        "/api/v1/zalo/cart/update",
        type="http",
        auth="public",
        methods=["PUT"],
        csrf=False,
    )
    def cart_update(self, **params):
        """
        Cập nhật số lượng dòng trong giỏ.
        Body: {"contact_id": 1, "line_id": 12, "quantity": 3}
        """
        try:
            body = self._request_json()
            contact_id = self._parse_int(body.get("contact_id"))
            line_id = self._parse_int(body.get("line_id"))
            quantity = self._parse_float(body.get("quantity"), 0)

            if not contact_id or not line_id:
                return self._response_error("INVALID_INPUT", "Thiếu contact_id hoặc line_id")

            cart, error = self._get_or_create_cart(contact_id)
            if error:
                return self._response_error("NOT_FOUND", error, 404)

            line = cart.order_line.filtered(lambda l: l.id == line_id)
            if not line:
                return self._response_error("NOT_FOUND", "Dòng sản phẩm không tồn tại", 404)

            if quantity <= 0:
                line.unlink()
            else:
                line.write({"product_uom_qty": quantity})

            return self._response_success(self._cart_to_dict(cart))
        except Exception as e:
            _logger.exception("cart_update error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # =========================================================================
    # DELETE /api/v1/zalo/cart/remove
    # =========================================================================
    @http.route(
        "/api/v1/zalo/cart/remove",
        type="http",
        auth="public",
        methods=["DELETE"],
        csrf=False,
    )
    def cart_remove(self, **params):
        """
        Xóa sản phẩm khỏi giỏ.
        Body: {"contact_id": 1, "line_id": 12}
        """
        try:
            body = self._request_json()
            contact_id = self._parse_int(body.get("contact_id"))
            line_id = self._parse_int(body.get("line_id"))

            if not contact_id or not line_id:
                return self._response_error("INVALID_INPUT", "Thiếu contact_id hoặc line_id")

            cart, error = self._get_or_create_cart(contact_id)
            if error:
                return self._response_error("NOT_FOUND", error, 404)

            line = cart.order_line.filtered(lambda l: l.id == line_id)
            if line:
                line.unlink()

            return self._response_success(self._cart_to_dict(cart))
        except Exception as e:
            _logger.exception("cart_remove error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # =========================================================================
    # DELETE /api/v1/zalo/cart/clear/<contact_id>
    # =========================================================================
    @http.route(
        "/api/v1/zalo/cart/clear/<int:contact_id>",
        type="http",
        auth="public",
        methods=["DELETE"],
        csrf=False,
    )
    def cart_clear(self, contact_id, **params):
        """Xóa toàn bộ giỏ hàng."""
        try:
            cart, error = self._get_or_create_cart(contact_id)
            if error:
                return self._response_error("NOT_FOUND", error, 404)

            cart.order_line.unlink()
            return self._response_success({"message": "Đã xóa giỏ hàng"})
        except Exception as e:
            _logger.exception("cart_clear error")
            return self._response_error("SERVER_ERROR", str(e), 500)