# -*- coding: utf-8 -*-
import logging
import re
from datetime import timedelta, timezone
from markupsafe import Markup

from odoo import _, fields, http
from odoo.http import request, Response

from .base_api import ZaloBaseAPI

_logger = logging.getLogger(__name__)

# GMT+7 timezone
GMT7 = timezone(timedelta(hours=7))


class ZaloOrderAPI(ZaloBaseAPI, http.Controller):
    """API Đơn hàng cho Zalo Mini App"""

    @staticmethod
    def _now_gmt7():
        """Return current datetime in GMT+7 as string."""
        return fields.Datetime.now().astimezone(GMT7).strftime("%Y-%m-%d %H:%M:%S")

    def _order_to_dict(self, order):
        lines = []
        voucher_discount_total = 0.0
        for line in order.order_line:
            is_voucher_line = False
            code = (line.product_id.default_code or "").upper() if line.product_id else ""
            name = (line.name or "").lower()
            if code in ("LOYALTY_VOUCHER_DISCOUNT", "VOUCHER_DISCOUNT") or "voucher" in name or "giảm giá" in name:
                is_voucher_line = True
            elif line.price_subtotal < 0 or line.price_unit < 0:
                is_voucher_line = True

            if is_voucher_line:
                voucher_discount_total += abs(line.price_subtotal or (line.price_unit * line.product_uom_qty))
            else:
                line_dict = {
                    "id": line.id,
                    "product_id": line.product_id.id if line.product_id else None,
                    "product_name": line.product_id.display_name if line.product_id else "",
                    "default_code": line.product_id.default_code if line.product_id else "",
                    "quantity": line.product_uom_qty,
                    "price_unit": line.price_unit,
                    "subtotal": line.price_subtotal,
                    "discount": line.discount or 0.0,
                }
                if hasattr(line, "loyalty_discount_pct"):
                    line_dict["loyalty_discount_pct"] = getattr(line, "loyalty_discount_pct", 0.0) or 0.0
                if hasattr(line, "x_studio_loyalty_discount_amount"):
                    line_dict["x_studio_loyalty_discount_amount"] = getattr(line, "x_studio_loyalty_discount_amount", 0.0) or 0.0
                lines.append(line_dict)

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

        # Return info (chỉ cho đơn Zalo)
        is_zalo = bool(order.partner_id.x_is_zalo_account)
        return_info = {
            "return_requested": getattr(order, "x_return_requested", False) or False,
            "is_returnable": getattr(order, "x_is_returnable", True),
            "days_since_delivery": getattr(order, "x_days_since_delivery", 0),
        }
        if is_zalo and getattr(order, "x_return_requested", False):
            return_info.update({
                "return_state": order.x_return_state or "pending",
                "return_type": order.x_return_type or None,
                "return_category": getattr(order, "x_return_category", False) or None,
                "product_condition": getattr(order, "x_product_condition", False) or None,
                "return_refund_amount": order.x_return_refund_amount or 0,
                "return_rejected_reason": order.x_return_rejected_reason or "",
                "return_picking_name": order.x_return_picking_id.name if order.x_return_picking_id else None,
                "return_picking_state": order.x_return_picking_id.state if order.x_return_picking_id else None,
                "return_completed_date": order.x_return_completed_date or None,
            })

        return {
            "id": order.id, "name": order.name,
            "partner_id": order.partner_id.id, "partner_name": order.partner_id.name,
            "partner_phone": order.partner_id.phone or "",
            "state": order.state, "date_order": order.date_order,
            "amount_untaxed": order.amount_untaxed, "amount_tax": order.amount_tax,
            "amount_total": order.amount_total, "note": order.note or "",
            "voucher_discount": voucher_discount_total,
            "loyalty_voucher_code": getattr(order, "loyalty_voucher_code", "") or "",
            **return_info,
            "lines": lines, "picking_info": picking_info,
            "shipping_address": {
                "name": order.partner_shipping_id.name or "",
                "phone": order.partner_shipping_id.phone or "",
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
            if order_amount < voucher.min_order_amount:
                return {"valid": False, "error": f"Đơn hàng tối thiểu {voucher.min_order_amount:,.0f}₫"}

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
        """Body: {"contact_id":1, "items":[{"product_id":42,"quantity":2}], "address_id":2, "note":"...", "voucher_code":"VHQ-XXXXX", "payment_method":"cod|zalopay"}
        
        items: Danh sách sản phẩm từ frontend (frontend tự quản lý giỏ hàng)
        payment_method: để ghi log, không ảnh hưởng flow xử lý
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
            payment_method = (body.get("payment_method") or "cod").strip().lower()

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

                # Ưu tiên dùng price_unit từ frontend (giá Zalo đã bao gồm VAT)
                # Nếu frontend không gửi, fallback về x_zalo_price hoặc list_price
                price = item.get("price_unit") or product.x_zalo_price or product.list_price
                order_line_vals.append((0, 0, {
                    "product_id": product_id,
                    "product_uom_qty": quantity,
                    "price_unit": price,
                    "tax_id": [(5, 0, 0)],  # Không áp thuế - giá Zalo đã bao gồm VAT
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
                    order.loyalty_voucher_code = voucher_code
                    order.action_apply_loyalty_voucher()
                except Exception as ve:
                    _logger.warning("Voucher apply error: %s", ve)
                    order.write({"note": (order.note or "") + f"\nVoucher: {voucher_code}"})

            # Luôn confirm đơn hàng ngay sau khi tạo (COD: user đã xác nhận, ZaloPay: đã thanh toán thành công)
            try:
                order.action_confirm()
            except Exception as ce:
                _logger.exception("Order confirm error")
                order.unlink()
                return self._response_error("ORDER_ERROR", f"Không thể xác nhận đơn: {str(ce)}", 400)

            order.write({"date_order": fields.Datetime.now()})

            # Parse customer note: extract real note text (remove [PTTT: ...] prefix added by frontend)
            customer_note = ""
            if note:
                # Frontend sends: "[PTTT: COD] - Ghi chú: abc..." or "[PTTT: ZaloPay] abc..."
                # Extract only the actual customer note part
                customer_note = re.sub(r'^\[PTTT:\s*[^\]]+\]\s*(?:-\s*Ghi chú:\s*)?', '', note).strip()
                if customer_note.startswith("- Ghi chú: "):
                    customer_note = customer_note[10:].strip()

            # Ghi log Chatter thông báo đơn hàng được tạo từ Zalo Mini App
            try:
                chatter_msg = Markup(_(
                    "<b>Đơn hàng được tạo từ Zalo Mini App</b><br/>"
                    "• <b>Khách hàng:</b> %s (SĐT: %s)<br/>"
                    "• <b>Thời gian tạo:</b> %s<br/>"
                    "• <b>Phương thức thanh toán:</b> %s"
                )) % (
                    partner.name,
                    partner.phone or partner.mobile or "N/A",
                    self._now_gmt7(),
                    payment_method.upper(),
                )
                if customer_note:
                    chatter_msg += Markup(_("<br/>• <b>Ghi chú từ khách hàng:</b> %s")) % customer_note
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
        """Body: {"order_id": 1, "reason": "Đổi ý"}"""
        if request.httprequest.method == "OPTIONS":
            return self._response_options()
        try:
            body = self._request_json()
            order_id = self._parse_int(body.get("order_id"), 0)
            reason = (body.get("reason") or "").strip()

            if not order_id:
                return self._response_error("INVALID_INPUT", "Thiếu order_id")

            # Auth: xác thực token (không cần contact_id từ client)
            auth_result = self._auth_required()
            if isinstance(auth_result, Response):
                return auth_result
            token_partner_id = auth_result

            order = request.env["sale.order"].sudo().browse(order_id)
            if not order.exists():
                return self._response_error("NOT_FOUND", "Đơn hàng không tồn tại", 404)

            # Ownership check: order phải thuộc về partner từ token
            if order.partner_id.id != token_partner_id:
                return self._response_error("FORBIDDEN", "Đơn hàng không thuộc về bạn", 403)

            if order.state in ("done", "cancel"):
                return self._response_error("INVALID_STATE", "Đơn hàng đã hoàn thành hoặc đã hủy", 400)

            if reason:
                order.write({"note": (order.note or "") + f"\nLý do hủy: {reason}"})

            # Force cancel với sudo() toàn diện để bypass ACL stock.picking / stock.move
            order_sudo = order.sudo()
            try:
                # Hủy tất cả picking chưa done/cancel
                pickings_to_cancel = order_sudo.picking_ids.filtered(
                    lambda p: p.state not in ('done', 'cancel')
                )
                if pickings_to_cancel:
                    # Hủy stock.move trước để tránh constraint
                    pickings_to_cancel.move_ids.filtered(
                        lambda m: m.state not in ('done', 'cancel')
                    ).write({'state': 'cancel'})
                    pickings_to_cancel.write({'state': 'cancel'})
            except Exception as e:
                _logger.warning("Force cancel pickings error: %s", e)

            # Set trực tiếp order state về cancel và tự động bật Cần hủy (x_plan_need_cancel)
            cancel_vals = {"state": "cancel"}
            if "x_plan_need_cancel" in order_sudo._fields:
                cancel_vals["x_plan_need_cancel"] = True
            order_sudo.write(cancel_vals)

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
        """Body: {"order_id": 1, "action_type": "received" | "return", "note": "Đã nhận hàng"}
        Phía Odoo chỉ nhận thông tin và ghi chép vào chatter/note, KHÔNG thực hiện action tự động nào khác.
        """
        if request.httprequest.method == "OPTIONS":
            return self._response_options()
        try:
            body = self._request_json()
            order_id = self._parse_int(body.get("order_id"), 0)
            action_type = (body.get("action_type") or "received").strip()
            note = (body.get("note") or "").strip()

            if not order_id:
                return self._response_error("INVALID_INPUT", "Thiếu order_id")

            # Auth: xác thực token (không cần contact_id từ client)
            auth_result = self._auth_required()
            if isinstance(auth_result, Response):
                return auth_result
            token_partner_id = auth_result

            order = request.env["sale.order"].sudo().browse(order_id)
            if not order.exists():
                return self._response_error("NOT_FOUND", "Đơn hàng không tồn tại", 404)

            # Ownership check: order phải thuộc về partner từ token
            if order.partner_id.id != token_partner_id:
                return self._response_error("FORBIDDEN", "Đơn hàng không thuộc về bạn", 403)

            title = "Xác nhận đã nhận được hàng" if action_type == "received" else "Đề nghị Đổi/Trả hàng"
            formatted_msg = Markup(_("<b>%s từ Zalo Mini App</b>")) % title
            if note:
                formatted_msg += Markup(_("<br/>• <b>Ghi chú từ khách hàng:</b> %s")) % note

            current_note = order.note or ""
            new_entry = f"\n[{self._now_gmt7()}] {title}"
            if note:
                new_entry += f": {note}"
            order.write({"note": current_note + new_entry})

            if action_type == "return":
                if hasattr(order, "x_is_returnable") and not order.x_is_returnable:
                    return self._response_error("EXPIRED_RETURN", "Đơn hàng đã quá thời hạn 7 ngày đổi/trả theo chính sách của Hoàng Long Vũ", 400)

                # Tìm phiếu giao hàng (OUT) cụ thể để gắn yêu cầu đổi/trả
                target_picking_id = self._parse_int(body.get("picking_id"), 0)
                target_picking = None
                if target_picking_id:
                    target_picking = order.picking_ids.filtered(lambda p: p.id == target_picking_id)
                if not target_picking:
                    # Lấy phiếu xuất kho (outgoing) đã done mới nhất
                    target_picking = order.picking_ids.filtered(
                        lambda p: p.picking_type_id.code == "outgoing" and p.state == "done"
                    )[:1]
                if not target_picking:
                    # Fallback lấy phiếu xuất kho bất kỳ chưa bị hủy
                    target_picking = order.picking_ids.filtered(
                        lambda p: p.picking_type_id.code == "outgoing" and p.state != "cancel"
                    )[:1]

                if target_picking:
                    return_type = (body.get("return_type") or "return").strip()
                    return_category = (body.get("return_category") or "supplier_fault").strip()
                    product_condition = (body.get("product_condition") or "unused").strip()

                    target_picking.sudo().write({
                        "x_zalo_return_requested": True,
                        "x_zalo_return_state": "pending",
                        "x_zalo_return_type": return_type if return_type in ("return", "exchange", "refund") else "return",
                        "x_zalo_return_category": return_category if return_category in ("supplier_fault", "customer_demand") else "supplier_fault",
                        "x_zalo_product_condition": product_condition if product_condition in ("unused", "used") else "unused",
                        "x_zalo_return_note": note,
                    })
                    try:
                        cat_label = "Lỗi nhà cung cấp / Vận chuyển" if return_category == "supplier_fault" else "Theo nhu cầu khách hàng"
                        cond_label = "Chưa qua sử dụng (nguyên tem)" if product_condition == "unused" else "Đã qua sử dụng"
                        picking_msg = Markup(_(
                            "<b>Yêu cầu Đổi/Trả hàng từ Zalo Mini App cho phiếu xuất %s</b><br/>"
                            "• <b>Phân loại:</b> %s<br/>"
                            "• <b>Tình trạng sản phẩm:</b> %s"
                        )) % (target_picking.name, cat_label, cond_label)
                        if note:
                            picking_msg += Markup(_("<br/>• <b>Ghi chú:</b> %s")) % note
                        target_picking.message_post(body=picking_msg, message_type="comment", subtype_xmlid="mail.mt_note")
                    except Exception as pme:
                        _logger.warning("Post chatter error on stock.picking %s: %s", target_picking.id, pme)

                    try:
                        target_picking.sudo()._send_zalo_return_notifications()
                    except Exception as ne:
                        _logger.exception("Error triggering return notifications for picking %s: %s", target_picking.id, ne)

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