# -*- coding: utf-8 -*-
import logging
from datetime import timedelta, timezone

from odoo import fields, http
from odoo.http import request

from .base_api import ZaloBaseAPI

_logger = logging.getLogger(__name__)


class ZaloOrderAPI(ZaloBaseAPI, http.Controller):
    """API Đơn hàng cho Zalo Mini App"""

    def _order_to_dict(self, order):
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
                    "id": picking.id, "type": picking.picking_type_id.name or "",
                    "state": picking.state, "scheduled_date": picking.scheduled_date,
                })
        except Exception:
            pass

        return {
            "id": order.id, "name": order.name,
            "partner_id": order.partner_id.id, "partner_name": order.partner_id.name,
            "partner_phone": order.partner_id.phone or "",
            "state": order.state, "date_order": order.date_order,
            "amount_untaxed": order.amount_untaxed, "amount_tax": order.amount_tax,
            "amount_total": order.amount_total, "note": order.note or "",
            "lines": lines, "picking_info": picking_info,
            "shipping_address": {
                "street": order.partner_shipping_id.street or "",
                "city": order.partner_shipping_id.city or "",
            } if order.partner_shipping_id else None,
        }

    def _verify_voucher_code(self, code, partner_id, order_amount=0):
        try:
            Voucher = request.env["hlv.loyalty.voucher"].sudo()
            voucher = Voucher.search([("code", "=", code)], limit=1)
            if not voucher:
                return {"valid": False, "error": "Mã voucher không tồn tại"}
            if voucher.state != "active":
                return {"valid": False, "error": "Voucher không còn hiệu lực"}
            if voucher.partner_id.id != partner_id:
                partner = request.env["res.partner"].sudo().browse(partner_id)
                parent = partner.parent_id
                if not parent or parent.id != voucher.partner_id.id:
                    return {"valid": False, "error": "Voucher không thuộc về bạn"}
            if voucher.date_expiry:
                now = fields.Datetime.now()
                if voucher.date_expiry < now:
                    return {"valid": False, "error": "Voucher đã hết hạn"}
            if order_amount < voucher.min_amount:
                return {"valid": False, "error": f"Đơn hàng tối thiểu {voucher.min_amount:,.0f}₫"}

            discount_value = 0
            if voucher.discount_type == "percent":
                discount_value = order_amount * voucher.discount_value / 100
                if voucher.max_discount_amount > 0:
                    discount_value = min(discount_value, voucher.max_discount_amount)
            else:
                discount_value = voucher.discount_value

            return {"valid": True, "voucher_code": voucher.code,
                    "discount_type": voucher.discount_type, "discount_value": voucher.discount_value,
                    "estimated_discount": discount_value}
        except Exception as e:
            _logger.warning("Voucher verification error: %s", e)
            return {"valid": False, "error": "Không thể kiểm tra voucher"}

    # POST /api/v1/zalo/orders/list
    @http.route("/api/v1/zalo/orders/list", type="http", auth="public", methods=["POST"], csrf=False)
    def order_list(self, **params):
        """Body: {"contact_id": 1, "limit": 20, "offset": 0, "state": "sale"}"""
        try:
            body = self._request_json()
            contact_id = self._parse_int(body.get("contact_id"), 0)
            try:
                limit, offset = self._parse_limit_offset(body, default_limit=20, max_limit=100)
            except ValueError as e:
                return self._response_error("INVALID_INPUT", str(e))
            state_filter = (body.get("state") or "").strip()

            if not contact_id:
                return self._response_error("INVALID_INPUT", "Thiếu contact_id")

            partner = request.env["res.partner"].sudo().browse(contact_id)
            if not partner.exists():
                return self._response_error("NOT_FOUND", "Khách hàng không tồn tại", 404)

            domain = [("partner_id", "=", contact_id), ("state", "!=", "draft")]
            if state_filter:
                domain.append(("state", "=", state_filter))

            orders = request.env["sale.order"].sudo().search(domain, limit=limit, offset=offset, order="date_order desc")
            total = request.env["sale.order"].sudo().search_count(domain)

            return self._response_success({
                "total": total, "limit": limit, "offset": offset,
                "orders": [self._order_to_dict(o) for o in orders],
            })
        except Exception as e:
            _logger.exception("order_list error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # POST /api/v1/zalo/orders/detail
    @http.route("/api/v1/zalo/orders/detail", type="http", auth="public", methods=["POST"], csrf=False)
    def order_detail(self, **params):
        """Body: {"order_id": 1}"""
        try:
            body = self._request_json()
            order_id = self._parse_int(body.get("order_id"), 0)
            if not order_id:
                return self._response_error("INVALID_INPUT", "Thiếu order_id")

            order = request.env["sale.order"].sudo().browse(order_id)
            if not order.exists():
                return self._response_error("NOT_FOUND", "Đơn hàng không tồn tại", 404)

            return self._response_success(self._order_to_dict(order))
        except Exception as e:
            _logger.exception("order_detail error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # POST /api/v1/zalo/orders/create
    @http.route("/api/v1/zalo/orders/create", type="http", auth="public", methods=["POST"], csrf=False)
    def order_create(self, **params):
        """Body: {"contact_id":1, "items":[{"product_id":42,"quantity":2}], "address_id":2, "note":"...", "voucher_code":"VHQ-XXXXX"}
        
        items: Danh sách sản phẩm từ frontend (frontend tự quản lý giỏ hàng)
        """
        try:
            body = self._request_json()
            contact_id = self._parse_int(body.get("contact_id"))
            items = body.get("items") or []
            address_id = self._parse_int(body.get("address_id"), 0)
            note = (body.get("note") or "").strip()
            voucher_code = (body.get("voucher_code") or "").strip()

            if not contact_id:
                return self._response_error("INVALID_INPUT", "Thiếu contact_id")

            if not items or not isinstance(items, list):
                return self._response_error("INVALID_INPUT", "Thiếu danh sách sản phẩm (items)", 400)

            partner = request.env["res.partner"].sudo().browse(contact_id)
            if not partner.exists():
                return self._response_error("NOT_FOUND", "Khách hàng không tồn tại", 404)

            # Validate và build order line values
            Product = request.env["product.product"].sudo()
            order_line_vals = []
            for item in items:
                product_id = self._parse_int(item.get("product_id"), 0)
                quantity = self._parse_float(item.get("quantity"), 0)
                if not product_id or quantity <= 0:
                    continue
                product = Product.browse(product_id)
                if not product.exists() or not product.active or not product.x_active_zalo:
                    continue
                price = product.x_zalo_price or product.list_price
                order_line_vals.append((0, 0, {
                    "product_id": product_id,
                    "product_uom_qty": quantity,
                    "price_unit": price,
                    "name": product.display_name,
                }))

            if not order_line_vals:
                return self._response_error("INVALID_INPUT", "Không có sản phẩm hợp lệ để tạo đơn", 400)

            # Tạo sale.order mới
            order_vals = {
                "partner_id": contact_id,
                "partner_invoice_id": address_id or contact_id,
                "partner_shipping_id": address_id or contact_id,
                "state": "draft",
                "order_line": order_line_vals,
            }
            if note:
                order_vals["note"] = note

            SaleOrder = request.env["sale.order"].sudo()
            order = SaleOrder.create(order_vals)

            # Tính tổng tiền cho voucher
            voucher_info = None
            if voucher_code:
                order_total = sum(l.price_subtotal for l in order.order_line)
                voucher_result = self._verify_voucher_code(voucher_code, contact_id, order_total)
                if not voucher_result["valid"]:
                    order.unlink()
                    return self._response_error("VOUCHER_ERROR", voucher_result["error"], 400)
                voucher_info = voucher_result
                try:
                    order.action_apply_loyalty_voucher(voucher_code)
                except Exception as ve:
                    _logger.warning("Voucher apply error: %s", ve)
                    order.write({"note": (order.note or "") + f"\nVoucher: {voucher_code}"})

            # Gán pricelist
            try:
                pricelist = request.env["product.pricelist"].sudo().search([("active", "=", True)], limit=1, order="id")
                if pricelist:
                    order.write({"pricelist_id": pricelist.id})
            except Exception:
                pass

            # Confirm đơn hàng
            try:
                order.action_confirm()
            except Exception as ce:
                _logger.exception("Order confirm error")
                order.unlink()
                return self._response_error("ORDER_ERROR", f"Không thể xác nhận đơn: {str(ce)}", 400)

            order.write({"state": "sale", "date_order": fields.Datetime.now()})

            result = self._order_to_dict(order)
            if voucher_info:
                result["voucher_applied"] = voucher_info

            return self._response_success(result, 201)
        except Exception as e:
            _logger.exception("order_create error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # POST /api/v1/zalo/orders/cancel
    @http.route("/api/v1/zalo/orders/cancel", type="http", auth="public", methods=["POST"], csrf=False)
    def order_cancel(self, **params):
        """Body: {"order_id": 1, "contact_id": 1, "reason": "Đổi ý"}"""
        try:
            body = self._request_json()
            order_id = self._parse_int(body.get("order_id"), 0)
            contact_id = self._parse_int(body.get("contact_id"), 0)
            reason = (body.get("reason") or "").strip()

            if not order_id or not contact_id:
                return self._response_error("INVALID_INPUT", "Thiếu order_id hoặc contact_id")

            order = request.env["sale.order"].sudo().browse(order_id)
            if not order.exists():
                return self._response_error("NOT_FOUND", "Đơn hàng không tồn tại", 404)

            if order.partner_id.id != contact_id:
                return self._response_error("FORBIDDEN", "Đơn hàng không thuộc về bạn", 403)

            if order.state in ("done", "cancel"):
                return self._response_error("INVALID_STATE", "Đơn hàng đã hoàn thành hoặc đã hủy", 400)

            if reason:
                order.write({"note": (order.note or "") + f"\nLý do hủy: {reason}"})

            # Gọi action_cancel, nếu thất bại thì force cancel
            try:
                order.action_cancel()
            except Exception:
                pass

            # Kiểm tra state thực tế, nếu chưa về "cancel" thì force
            if order.state != "cancel":
                # Hủy các picking liên quan trước
                try:
                    order.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel')).action_cancel()
                except Exception:
                    pass
                order.write({"state": "cancel"})

            return self._response_success({
                "id": order.id, "name": order.name, "state": order.state,
                "message": "Đã hủy đơn hàng thành công",
            })
        except Exception as e:
            _logger.exception("order_cancel error")
            return self._response_error("SERVER_ERROR", str(e), 500)