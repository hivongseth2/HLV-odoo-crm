# -*- coding: utf-8 -*-
"""Khách tự nhận quà Loyalty trên Mini App: một đơn riêng chỉ có món quà 0đ.

Voucher Quà tặng không dùng được khi mua hàng (hlv_loyalty bắt nó nằm trên đơn
không có hàng bán) — đơn này là nơi duy nhất khách dùng được nó. Giao xong thì
đơn đi luồng đẩy chứng từ khuyến mại sang MISA của amis_callback.
"""
import logging

from markupsafe import Markup

from odoo import fields, http
from odoo.http import request, Response

from .base_api import ZaloBaseAPI
from .order_api import ZaloOrderAPI
from .voucher_apply import voucher_apply_error

_logger = logging.getLogger(__name__)

GIFT_PAYMENT_LABEL = "QUÀ TẶNG"


class ZaloGiftOrderAPI(ZaloBaseAPI, http.Controller):

    # POST /api/v1/zalo/loyalty/gift-order
    @http.route("/api/v1/zalo/loyalty/gift-order", type="http", auth="public",
                methods=["POST", "OPTIONS"], csrf=False)
    def gift_order_create(self, **params):
        """Body: {"contact_id": 1, "voucher_code": "VHQ-XXXXXX", "address_id": 2, "note": "..."}

        Trả về đơn đã xác nhận (cùng định dạng /orders/create), lỗi VOUCHER_ERROR
        nếu mã không nhận quà được.
        """
        if request.httprequest.method == "OPTIONS":
            return self._response_options()
        try:
            body = self._request_json()
            contact_id = self._parse_int(body.get("contact_id"))
            voucher_code = (body.get("voucher_code") or "").strip().upper()
            address_id = self._parse_int(body.get("address_id"), 0)
            note = (body.get("note") or "").strip()

            if not contact_id or not voucher_code:
                return self._response_error("INVALID_INPUT", "Thiếu contact_id hoặc mã quà tặng")

            auth_result = self._auth_and_verify_owner(contact_id)
            if isinstance(auth_result, Response):
                return auth_result

            partner = request.env["res.partner"].sudo().browse(contact_id)
            if not partner.exists():
                return self._response_error("NOT_FOUND", "Khách hàng không tồn tại", 404)
            shipping = self._owned_address(partner, address_id)
            if not shipping:
                return self._response_error("FORBIDDEN", "Địa chỉ giao hàng không hợp lệ", 403)

            voucher = request.env["hlv.loyalty.voucher"].sudo().search(
                [("code", "=", voucher_code)], limit=1,
            )
            error = self._gift_voucher_error(voucher)
            if error:
                return self._response_error("VOUCHER_ERROR", error, 400)

            order = self._create_gift_order(partner, shipping, note)
            voucher_error = voucher_apply_error(order, voucher_code)
            if voucher_error:
                order.unlink()
                return self._response_error("VOUCHER_ERROR", voucher_error, 400)
            try:
                order.action_confirm()
            except Exception as ce:
                _logger.exception("Gift order confirm error")
                order.unlink()
                return self._response_error("ORDER_ERROR", f"Không thể xác nhận đơn quà: {ce}", 400)
            order.write({"date_order": fields.Datetime.now()})

            self._announce_gift_order(order, partner, voucher, note)
            return self._response_success(ZaloOrderAPI._order_to_dict(order), 201)
        except Exception as e:
            _logger.exception("gift_order_create error")
            return self._response_error("SERVER_ERROR", str(e), 500)

    def _gift_voucher_error(self, voucher):
        """Lý do mã không nhận quà qua Mini App được, '' nếu được.

        Chỉ kiểm những gì riêng của kênh này (loại mã, tài khoản, tồn kho). Hạn
        dùng, chủ sở hữu, đã dùng chưa... do action_apply_loyalty_voucher kiểm.
        """
        if not voucher:
            return "Mã quà tặng không tồn tại."
        if voucher.reward_type != "gift":
            return "Mã này không phải mã quà tặng — hãy dùng khi thanh toán giỏ hàng."
        # Voucher đổi bằng một tài khoản Loyalty thì chỉ tài khoản đó nhận quà
        # (cùng quy tắc với danh sách ví voucher).
        if voucher.account_id and voucher.account_id.id != self._auth_account_id():
            return "Mã quà tặng này không thuộc tài khoản của bạn."
        product = voucher.gift_product_id
        if product and product.is_storable and product.free_qty < (voucher.gift_qty or 1):
            return f"Quà '{product.display_name}' tạm hết hàng, vui lòng liên hệ cửa hàng."
        return ""

    def _create_gift_order(self, partner, shipping, note):
        vals = {
            "partner_id": partner.id,
            "partner_invoice_id": shipping.id,
            "partner_shipping_id": shipping.id,
            "x_zalo_payment_method": GIFT_PAYMENT_LABEL,
        }
        account_id = self._auth_account_id()
        if account_id:
            vals["x_zalo_portal_account_id"] = account_id
        pricelist = self._zalo_pricelist()
        if pricelist:
            vals["pricelist_id"] = pricelist.id
        if note:
            vals["note"] = note
        return request.env["sale.order"].sudo().create(vals)

    def _announce_gift_order(self, order, partner, voucher, note):
        try:
            body = Markup(
                "<b>Đơn quà tặng Loyalty khách tự nhận trên Zalo Mini App</b><br/>"
                "• <b>Khách hàng:</b> %s (SĐT: %s)<br/>"
                "• <b>Voucher:</b> %s — %s x %s"
            ) % (
                partner.name,
                partner.phone or partner.mobile or "N/A",
                voucher.code,
                voucher.gift_qty or 1,
                voucher.gift_product_id.display_name,
            )
            if note:
                body += Markup("<br/>• <b>Ghi chú từ khách hàng:</b> %s") % note
            order.message_post(body=body, message_type="comment", subtype_xmlid="mail.mt_note")
        except Exception as me:
            _logger.warning("Post chatter error on gift order %s: %s", order.id, me)

        self._notify_order_to_discuss_channel(order, payment_method=GIFT_PAYMENT_LABEL, customer_note=note)
        self._send_order_zalo_notification_message(order, payment_method=GIFT_PAYMENT_LABEL, customer_note=note)
        self._send_order_zns_notification(order)
