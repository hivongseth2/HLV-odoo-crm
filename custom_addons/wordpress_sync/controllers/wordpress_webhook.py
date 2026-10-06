# -*- coding: utf-8 -*-
import json
import logging

from odoo import http
from odoo.http import Response, request

from ..models.wordpress_sync_utils import wc_signature_valid

_logger = logging.getLogger(__name__)


class WordPressProductWebhook(http.Controller):
    """
    Nhận webhook sản phẩm (created/updated/deleted/restored) của WooCommerce để cập nhật
    bảng liên kết ngay, không phải chờ lượt quét đêm.
    """

    @http.route(
        "/api/wordpress_sync/webhook/<int:config_id>",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def product_webhook(self, config_id, **kwargs):
        config = request.env["wordpress.config"].sudo().browse(config_id).exists()
        if not config or not config.active:
            return self._reply({"ok": False, "error": "config_not_found"}, status=404)

        headers = request.httprequest.headers
        topic = headers.get("X-WC-Webhook-Topic", "")
        if not topic:
            # Khi lưu webhook, WooCommerce gửi ping 'webhook_id=<id>' không topic, không chữ ký;
            # phải trả 200 thì WooCommerce mới cho lưu. Ping không làm thay đổi gì.
            return self._reply({"ok": True, "ping": True})

        body = request.httprequest.get_data(cache=True)
        signature = headers.get("X-WC-Webhook-Signature", "")
        if not wc_signature_valid(body, config.get_webhook_secret(), signature):
            return self._reply({"ok": False, "error": "invalid_signature"}, status=401)

        try:
            payload = json.loads(body or b"{}")
            with request.env.cr.savepoint():
                request.env["wordpress.product.link"].sudo()._apply_webhook(config, topic, payload)
        except Exception:
            _logger.exception("Webhook %s cho %s lỗi", topic, config.name)
            # Vẫn trả 200: WooCommerce tự tắt webhook sau 5 lần lỗi liên tiếp. Lượt quét
            # hằng đêm sẽ sửa lại dòng bị lỡ.
            return self._reply({"ok": False, "error": "apply_failed"})

        return self._reply({"ok": True})

    def _reply(self, data, status=200):
        return Response(json.dumps(data), status=status, content_type="application/json")
