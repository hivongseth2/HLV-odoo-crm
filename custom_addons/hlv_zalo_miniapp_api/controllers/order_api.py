# -*- coding: utf-8 -*-
import json
import logging
from datetime import timedelta, timezone

from odoo import fields, http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class ZaloOrderAPI(http.Controller):
    """API Đơn hàng cho Zalo Mini App"""

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

    def _order_to_dict(self, order):
        """Convert sale.order to API response dict."""
        lines = []
        for line in order.order_line:
            lines.append({
                "id": line.id,
                "product_id": line.product_id.id if line.product_id else None,
                "product_name": line.product_id.display_name if line.product_id else "",
                "default_code": line.product_id.default_code if line.product_id else "",
                "quantity": line.product_uom_qty,
                "price_unit": line.price_unit,
                "subtotal": line.price_subtotal,
                "discount": line.discount or 0.0,
            })

        picking_info = []
        try:
            for picking in order.picking_ids.filtered(lambda p: p.state == "done"):
                picking_info.append({
                    "id": picking.id,
                    "type": picking.picking_type_id.name or "",
                    "state": picking.state,
                    "scheduled_date": picking.scheduled_date,
                })
        except Exception:
            pass

        return {
            "id": order.id,
            "name": order.name,
            "partner_id": order.partner_id.id,
            "partner_name": order.partner_id.name,
            "partner_phone": order.partner_id.phone or "",
            "state": order.state,
            "date_order": order.date_order,
            "amount_untaxed": order.amount_untaxed,
            "amount_tax": order.amount_tax,
            "amount_total": order.amount_total,
            "note": order.note or "",
            "lines": lines,
            "picking_info": picking_info,
            "shipping_address": {
                "street": order.partner_shipping_id.street or "",
                "city": order.partner_shipping_id.city or "",
            } if order.partner_shipping_id else None,
        }

    def _verify_voucher_code(self, code, partner_id, order_amount=0):
        """Verify loyalty voucher from hlv_loyalty module.
        Returns dict with valid flag and error message if invalid."""
        try:
            Voucher = request.env["hlv.loyalty.voucher"].sudo()
            voucher = Voucher.search([("code", "=", code)], limit=1)
            if not voucher:
                return {"valid": False, "error": "Mã voucher không tồn tại"}
            if voucher.state != "active":
                return {"valid": False, "error": "Voucher không còn hiệu lực"}
            if voucher.partner_id.id != partner_id:
                # Check if voucher belongs to a parent of this partner
                partner = request.env["res.partner"].sudo().browse(partner_id)
                parent = partner.parent_id
                if not parent or parent.id != voucher.partner_id.id:
                    return {"valid": False, "error": "Voucher không thuộc về bạn"}

            # Check expiry
            if voucher.date_expiry:
                now = fields.Datetime.now()
                if voucher.date_expiry < now:
                    return {"valid": False, "error": "Voucher đã hết hạn"}

            # Check minimum order
            if order_amount < voucher.min_amount:
                return {
                    "valid": False,
                    "error": f"Đơn hàng tối thiểu {voucher.min_amount:,.0f}₫",
                }

            # Apply discount estimate
            discount_value = 0
            if voucher.discount_type == "percent":
                discount_value = order_amount * voucher.discount_value / 100
                if voucher.max_discount_amount > 0:
                    discount_value = min(discount_value, voucher.max_discount_amount)
            else:
                discount_value = voucher.discount_value

            return {
                "valid": True,
                "voucher_code": voucher.code,
                "discount_type": voucher.discount_type,
                "discount_value": voucher.discount_value,
                "estimated_discount": discount_value,
            }
        except Exception as e:
            _logger.warning("Voucher verification error: %s", e)
            return {"valid": False, "error": "Không thể kiểm tra voucher"}

    # =========================================================================
    # GET /api/v1/zalo/orders/<contact_id>/list
    # =========================================================================
    @http.route(
        "/api/v1/zalo/orders/<int:contact_id>/list",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def order_list(self, contact_id, **params):
        """Danh sách đơn hàng của contact."""
        try:
            limit = self._parse_int(params.get("limit"), 20)
            offset = self._parse_int(params.get("offset"), 0)
            state_filter = (params.get("state") or "").strip()
            limit = min(max(limit, 1), 100)

            partner = request.env["res.partner"].sudo().browse(contact_id)
            if not partner.exists():
                return self._response_error("NOT_FOUND", "Khách hàng không tồn tại", 404)

            domain = [
                ("partner_id", "=", contact_id),
                ("state", "!=", "draft"),  # Exclude cart orders
            ]

            if state_filter:
                domain.append(("state", "=", state_filter))

            orders = request.env["sale.order"].sudo().search(
                domain, limit=limit, offset=offset, order="date_order desc"
            )
            total = request.env["sale.order"].sudo().search_count(domain)

            data = []
            for order in orders:
                data.append(self._order_to_dict(order))

            return self._response_success({
                "total": total,
                "limit": limit,
                "offset": offset,
                "orders": data,
            })
        except Exception as e:
            _logger.exception("order_list error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # =========================================================================
    # GET /api/v1/zalo/orders/<id>
    # =========================================================================
    @http.route(
        "/api/v1/zalo/orders/<int:order_id>",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def order_detail(self, order_id, **params):
        """Chi tiết đơn hàng."""
        try:
            order = request.env["sale.order"].sudo().browse(order_id)
            if not order.exists():
                return self._response_error("NOT_FOUND", "Đơn hàng không tồn tại", 404)

            return self._response_success(self._order_to_dict(order))
        except Exception as e:
            _logger.exception("order_detail error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # =========================================================================
    # POST /api/v1/zalo/orders/create
    # =========================================================================
    @http.route(
        "/api/v1/zalo/orders/create",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def order_create(self, **params):
        """
        Tạo đơn hàng từ giỏ hàng hiện tại.
        Body: {
            "contact_id": 1,
            "address_id": 2,
            "note": "Giao trước 18h",
            "voucher_code": "VHQ-XXXXX" (optional)
        }
        """
        try:
            body = self._request_json()
            contact_id = self._parse_int(body.get("contact_id"))
            address_id = self._parse_int(body.get("address_id"), 0)
            note = (body.get("note") or "").strip()
            voucher_code = (body.get("voucher_code") or "").strip()

            if not contact_id:
                return self._response_error("INVALID_INPUT", "Thiếu contact_id")

            partner = request.env["res.partner"].sudo().browse(contact_id)
            if not partner.exists():
                return self._response_error("NOT_FOUND", "Khách hàng không tồn tại", 404)

            # Get cart (draft SO)
            SaleOrder = request.env["sale.order"].sudo()
            cart = SaleOrder.search([
                ("partner_id", "=", contact_id),
                ("state", "=", "draft"),
            ], limit=1, order="id desc")

            if not cart or not cart.order_line:
                return self._response_error("INVALID_INPUT", "Giỏ hàng trống", 400)

            # Update cart with shipping address and note
            cart_vals = {}
            if address_id:
                address = request.env["res.partner"].sudo().browse(address_id)
                if address.exists():
                    cart_vals["partner_shipping_id"] = address_id
                    cart_vals["partner_invoice_id"] = address_id
            if note:
                cart_vals["note"] = note
            if cart_vals:
                cart.write(cart_vals)

            # Verify voucher if provided
            voucher_info = None
            if voucher_code:
                order_total = sum(l.price_subtotal for l in cart.order_line)
                voucher_result = self._verify_voucher_code(voucher_code, contact_id, order_total)
                if not voucher_result["valid"]:
                    return self._response_error("VOUCHER_ERROR", voucher_result["error"], 400)
                voucher_info = voucher_result

                # Apply voucher via hlv_loyalty
                try:
                    cart.action_apply_loyalty_voucher(voucher_code)
                except Exception as ve:
                    _logger.warning("Voucher apply error: %s", ve)
                    # Silently fail voucher apply - just record the code
                    cart.write({"note": (cart.note or "") + f"\nVoucher: {voucher_code}"})

            # Try to find a pricelist for the partner/contact
            try:
                pricelist = request.env["product.pricelist"].sudo().search([
                    ("active", "=", True),
                ], limit=1, order="id")
                if pricelist:
                    cart.write({"pricelist_id": pricelist.id})
            except Exception:
                pass

            # Confirm the order
            try:
                cart.action_confirm()
            except Exception as ce:
                _logger.exception("Order confirm error")
                return self._response_error("ORDER_ERROR", f"Không thể xác nhận đơn: {str(ce)}", 400)

            # Update state
            cart.write({"state": "sale", "date_order": fields.Datetime.now()})

            result = self._order_to_dict(cart)
            if voucher_info:
                result["voucher_applied"] = voucher_info

            return self._response_success(result, 201)
        except Exception as e:
            _logger.exception("order_create error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # =========================================================================
    # POST /api/v1/zalo/orders/<id>/cancel
    # =========================================================================
    @http.route(
        "/api/v1/zalo/orders/<int:order_id>/cancel",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def order_cancel(self, order_id, **params):
        """
        Hủy đơn hàng.
        Body: {"contact_id": 1, "reason": "Đổi ý"}
        """
        try:
            body = self._request_json()
            contact_id = self._parse_int(body.get("contact_id"))
            reason = (body.get("reason") or "").strip()

            if not contact_id:
                return self._response_error("INVALID_INPUT", "Thiếu contact_id")

            order = request.env["sale.order"].sudo().browse(order_id)
            if not order.exists():
                return self._response_error("NOT_FOUND", "Đơn hàng không tồn tại", 404)

            if order.partner_id.id != contact_id:
                return self._response_error("FORBIDDEN", "Đơn hàng không thuộc về bạn", 403)

            # Only allow cancel if draft or sent (not confirmed)
            if order.state not in ("draft", "sent"):
                return self._response_error(
                    "INVALID_STATE",
                    "Chỉ có thể hủy đơn hàng chưa xác nhận",
                    400,
                )

            if reason:
                order.write({"note": (order.note or "") + f"\nLý do hủy: {reason}"})

            order.action_cancel()

            return self._response_success({
                "id": order.id,
                "name": order.name,
                "state": order.state,
                "message": "Đã hủy đơn hàng thành công",
            })
        except Exception as e:
            _logger.exception("order_cancel error")
            return self._response_error("SERVER_ERROR", str(e), 500)