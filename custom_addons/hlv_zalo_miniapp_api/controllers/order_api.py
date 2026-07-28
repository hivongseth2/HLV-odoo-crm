# -*- coding: utf-8 -*-
import logging
from markupsafe import Markup

from odoo import _, fields, http
from odoo.http import request, Response

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
            for picking in order.picking_ids.filtered(lambda p: p.state != "cancel"):
                picking_info.append({
                    "id": picking.id,
                    "name": picking.name or "",
                    "code": picking.picking_type_id.code or "",
                    "type": picking.picking_type_id.name or "",
                    "state": picking.state,
                    "scheduled_date": picking.scheduled_date,
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
    @http.route("/api/v1/zalo/orders/list", type="http", auth="public", methods=["POST", "OPTIONS"], csrf=False)
    def order_list(self, **params):
        """Body: {"contact_id": 1, "limit": 20, "offset": 0, "state": "sale"}"""
        if request.httprequest.method == "OPTIONS":
            return self._response_options()
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

            # Auth + ownership check
            auth_result = self._auth_and_verify_owner(contact_id)
            if isinstance(auth_result, Response):
                return auth_result

            partner = request.env["res.partner"].sudo().browse(contact_id)
            if not partner.exists():
                return self._response_error("NOT_FOUND", "Khách hàng không tồn tại", 404)

            domain = [("partner_id", "=", contact_id), ("state", "!=", "draft")]
            if state_filter:
                if "," in state_filter:
                    states = [s.strip() for s in state_filter.split(",") if s.strip()]
                    domain.append(("state", "in", states))
                elif state_filter in ("sale", "done", "shipping", "processing"):
                    domain.append(("state", "in", ["sale", "done"]))
                else:
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
    @http.route("/api/v1/zalo/orders/detail", type="http", auth="public", methods=["POST", "OPTIONS"], csrf=False)
    def order_detail(self, **params):
        """Body: {"order_id": 1}"""
        if request.httprequest.method == "OPTIONS":
            return self._response_options()
        try:
            body = self._request_json()
            order_id = self._parse_int(body.get("order_id"), 0)
            if not order_id:
                return self._response_error("INVALID_INPUT", "Thiếu order_id")

            order = request.env["sale.order"].sudo().browse(order_id)
            if not order.exists():
                return self._response_error("NOT_FOUND", "Đơn hàng không tồn tại", 404)

            # Auth + ownership check: order phải thuộc về contact trong token
            contact_id = order.partner_id.id
            if not contact_id:
                return self._response_error("FORBIDDEN", "Đơn hàng không hợp lệ", 403)
            auth_result = self._auth_and_verify_owner(contact_id)
            if isinstance(auth_result, Response):
                return auth_result

            return self._response_success(self._order_to_dict(order))
        except Exception as e:
            _logger.exception("order_detail error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # POST /api/v1/zalo/orders/create
    @http.route("/api/v1/zalo/orders/create", type="http", auth="public", methods=["POST", "OPTIONS"], csrf=False)
    def order_create(self, **params):
        """Body: {"contact_id":1, "items":[{"product_id":42,"quantity":2}], "address_id":2, "note":"...", "voucher_code":"VHQ-XXXXX"}
        
        items: Danh sách sản phẩm từ frontend (frontend tự quản lý giỏ hàng)
        """
        if request.httprequest.method == "OPTIONS":
            return self._response_options()
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

            # Auth + ownership check
            auth_result = self._auth_and_verify_owner(contact_id)
            if isinstance(auth_result, Response):
                return auth_result

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

                # Validate tồn kho
                if product.free_qty < quantity:
                    return self._response_error("OUT_OF_STOCK",
                        f"Sản phẩm '{product.display_name}' chỉ còn {product.free_qty} {product.uom_id.name}", 400)

                price = product.x_zalo_price or product.list_price
                order_line_vals.append((0, 0, {
                    "product_id": product_id,
                    "product_uom_qty": quantity,
                    "price_unit": price,
                    "name": product.display_name,
                }))

            if not order_line_vals:
                return self._response_error("INVALID_INPUT", "Không có sản phẩm hợp lệ để tạo đơn", 400)

            # Gán pricelist trước khi tạo order
            pricelist_id = False
            try:
                pricelist = request.env["product.pricelist"].sudo().search([("active", "=", True)], limit=1, order="id")
                if pricelist:
                    pricelist_id = pricelist.id
            except Exception:
                pass

            # Tạo sale.order mới
            order_vals = {
                "partner_id": contact_id,
                "partner_invoice_id": address_id or contact_id,
                "partner_shipping_id": address_id or contact_id,
                "state": "draft",
                "order_line": order_line_vals,
            }
            if pricelist_id:
                order_vals["pricelist_id"] = pricelist_id
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

            # Confirm đơn hàng
            try:
                order.action_confirm()
            except Exception as ce:
                _logger.exception("Order confirm error")
                order.unlink()
                return self._response_error("ORDER_ERROR", f"Không thể xác nhận đơn: {str(ce)}", 400)

            # Không cần write state="sale" vì action_confirm() đã chuyển state
            order.write({"date_order": fields.Datetime.now()})

            # Ghi log Chatter thông báo đơn hàng được tạo từ Zalo Mini App
            try:
                chatter_msg = Markup(_(
                    "<b>Đơn hàng được tạo từ Zalo Mini App</b><br/>"
                    "• <b>Khách hàng:</b> %s (SĐT: %s)<br/>"
                    "• <b>Thời gian tạo:</b> %s"
                )) % (
                    partner.name,
                    partner.phone or partner.mobile or "N/A",
                    fields.Datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
                if note:
                    chatter_msg += Markup(_("<br/>• <b>Ghi chú:</b> %s")) % note
                if voucher_code:
                    chatter_msg += Markup(_("<br/>• <b>Voucher:</b> %s")) % voucher_code

                order.message_post(body=chatter_msg, message_type="comment", subtype_xmlid="mail.mt_note")
            except Exception as me:
                _logger.warning("Post chatter error on sale.order %s: %s", order.id, me)

            # Tự động dọn dẹp giỏ hàng tạm (zalo.miniapp.cart.line) của khách sau khi tạo đơn thành công
            try:
                CartLine = request.env["zalo.miniapp.cart.line"].sudo()
                cart_lines = CartLine.search([("partner_id", "=", contact_id)])
                if cart_lines:
                    cart_lines.unlink()
            except Exception as cle:
                _logger.warning("Clear cart after order create error: %s", cle)

            result = self._order_to_dict(order)
            if voucher_info:
                result["voucher_applied"] = voucher_info

            return self._response_success(result, 201)
        except Exception as e:
            _logger.exception("order_create error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # POST /api/v1/zalo/orders/cancel
    @http.route("/api/v1/zalo/orders/cancel", type="http", auth="public", methods=["POST", "OPTIONS"], csrf=False)
    def order_cancel(self, **params):
        """Body: {"order_id": 1, "contact_id": 1, "reason": "Đổi ý"}"""
        if request.httprequest.method == "OPTIONS":
            return self._response_options()
        try:
            body = self._request_json()
            order_id = self._parse_int(body.get("order_id"), 0)
            contact_id = self._parse_int(body.get("contact_id"), 0)
            reason = (body.get("reason") or "").strip()

            if not order_id or not contact_id:
                return self._response_error("INVALID_INPUT", "Thiếu order_id hoặc contact_id")

            # Auth + ownership check
            auth_result = self._auth_and_verify_owner(contact_id)
            if isinstance(auth_result, Response):
                return auth_result

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

            # Ghi log Chatter thông báo đơn hàng bị hủy từ Zalo Mini App
            try:
                cancel_msg = Markup(_("<b>Đơn hàng đã bị hủy từ Zalo Mini App</b>"))
                if reason:
                    cancel_msg += Markup(_("<br/>• <b>Lý do hủy:</b> %s")) % reason
                order.message_post(body=cancel_msg, message_type="comment", subtype_xmlid="mail.mt_note")
            except Exception as me:
                _logger.warning("Post cancel chatter error: %s", me)

            return self._response_success({
                "id": order.id, "name": order.name, "state": order.state,
                "message": "Đã hủy đơn hàng thành công",
            })
        except Exception as e:
            _logger.exception("order_cancel error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    # POST /api/v1/zalo/orders/feedback
    @http.route("/api/v1/zalo/orders/feedback", type="http", auth="public", methods=["POST", "OPTIONS"], csrf=False)
    def order_feedback(self, **params):
        """Body: {"order_id": 1, "contact_id": 1, "action_type": "received" | "return", "note": "Đã nhận hàng"}
        Phía Odoo chỉ nhận thông tin và ghi chép vào chatter/note, KHÔNG thực hiện action tự động nào khác.
        """
        if request.httprequest.method == "OPTIONS":
            return self._response_options()
        try:
            body = self._request_json()
            order_id = self._parse_int(body.get("order_id"), 0)
            contact_id = self._parse_int(body.get("contact_id"), 0)
            action_type = (body.get("action_type") or "received").strip()
            note = (body.get("note") or "").strip()

            if not order_id or not contact_id:
                return self._response_error("INVALID_INPUT", "Thiếu order_id hoặc contact_id")

            auth_result = self._auth_and_verify_owner(contact_id)
            if isinstance(auth_result, Response):
                return auth_result

            order = request.env["sale.order"].sudo().browse(order_id)
            if not order.exists():
                return self._response_error("NOT_FOUND", "Đơn hàng không tồn tại", 404)

            if order.partner_id.id != contact_id:
                return self._response_error("FORBIDDEN", "Đơn hàng không thuộc về bạn", 403)

            title = "Xác nhận đã nhận được hàng" if action_type == "received" else "Đề nghị Đổi/Trả hàng"
            formatted_msg = Markup(_("<b>%s từ Zalo Mini App</b>")) % title
            if note:
                formatted_msg += Markup(_("<br/>• <b>Ghi chú từ khách hàng:</b> %s")) % note

            current_note = order.note or ""
            new_entry = f"\n[{fields.Datetime.now().strftime('%Y-%m-%d %H:%M')}] {title}"
            if note:
                new_entry += f": {note}"
            order.write({"note": current_note + new_entry})

            try:
                order.message_post(body=formatted_msg, message_type="comment", subtype_xmlid="mail.mt_note")
            except Exception as me:
                _logger.warning("Post feedback chatter error: %s", me)

            return self._response_success({
                "id": order.id,
                "name": order.name,
                "message": f"Đã gửi thông tin: {title}",
            })
        except Exception as e:
            _logger.exception("order_feedback error")
            return self._response_error("SERVER_ERROR", str(e), 500)