# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)


VI_STATUS_LABELS = {
    "INFORECEIVED": "Đơn hàng đã được tạo trên hệ thống",
    "INTRANSIT": "Đang trung chuyển",
    "OUTFORDELIVERY": "Nhân viên đang giao hàng",
    "DELIVERED": "Đã giao thành công",
    "AVAILABLEFORPICKUP": "Sẵn sàng để lấy hàng",
    "FAILEDATTEMPT": "Giao hàng chưa thành công",
    "EXCEPTION": "Phát sinh sự cố trong quá trình giao",
    "PENDING": "Đang chờ hãng vận chuyển xử lý",
    "READYFORPICKUP": "Sẵn sàng để lấy hàng",
    "RETURNEDTOSELLER": "Đơn hàng đã được hoàn về",
}


REPLACEMENTS = (
    ("Thực tệ", "Đơn hàng"),
    ("Bưu kiện của bạn", "Kiện hàng của bạn"),
    ("đang được chuyển phát nhanh", "đang trên đường giao"),
    ("đã được nhận", "đã được tiếp nhận"),
)


def _polish_message(message: str) -> str:
    msg = (message or "").strip()
    for old, new in REPLACEMENTS:
        msg = msg.replace(old, new)
    return msg


def _vi_status(tag: str, fallback: str = "") -> str:
    key = (tag or "").replace(" ", "").upper()
    if key in VI_STATUS_LABELS:
        return VI_STATUS_LABELS[key]
    return fallback or tag or ""


class AfterShipWebhook(http.Controller):
    """
    Webhook handler to receive tracking updates from AfterShip
    
    AfterShip sẽ gửi POST request đến endpoint này khi có cập nhật về tracking.
    Endpoint: https://yourdomain.com/aftership/webhook
    
    Để kích hoạt webhook:
    1. Đăng ký webhook URL trong AfterShip dashboard hoặc qua API
    2. Đảm bảo 'aftership.webhook_secret' được cấu hình trong System Parameters (optional, để verify)
    """

    @http.route('/aftership/webhook', type='json', auth='public', methods=['POST'], csrf=False)
    def aftership_webhook_handler(self, **post):
        """
        Nhận và xử lý webhook từ AfterShip
        
        Payload mẫu từ AfterShip:
        {
            "msg": {
                "id": "...",
                "tracking_number": "JTXXX123456",
                "slug": "jtexpress-vn",
                "tag": "InTransit",
                "subtag": "InTransit_001",
                "checkpoints": [...],
                ...
            }
        }
        """
        try:
            payload = request.jsonrequest
            _logger.info(f"Received AfterShip webhook: {payload}")
            
            # Verify webhook secret (optional but recommended)
            webhook_secret = request.env['ir.config_parameter'].sudo().get_param('aftership.webhook_secret', '')
            if webhook_secret:
                # AfterShip gửi secret trong header 'aftership-hmac-sha256'
                received_signature = request.httprequest.headers.get('aftership-hmac-sha256', '')
                # TODO: Implement signature verification if needed
                # import hmac
                # import hashlib
                # expected_signature = hmac.new(webhook_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
            
            # Lấy thông tin tracking từ payload
            msg = payload.get('msg', {})
            tracking_number = msg.get('tracking_number', '').strip()
            slug = msg.get('slug', '').strip()
            tag = msg.get('tag') or msg.get('subtag') or msg.get('status')
            
            if not tracking_number:
                _logger.warning("AfterShip webhook: No tracking_number in payload")
                return {'status': 'error', 'message': 'No tracking_number'}
            
            # Tìm record trong database (stock.picking hoặc sale.order)
            Picking = request.env['stock.picking'].sudo()
            SaleOrder = request.env['sale.order'].sudo()
            
            # Tìm trong stock.picking
            picks = Picking.search([('tracking_number', '=', tracking_number)])
            if picks:
                for pick in picks:
                    pick.write({
                        'tracking_payload': msg,
                        'tracking_status': _vi_status(tag, tag),
                        'tracking_last_update': request.env['ir.fields'].Datetime.now(),
                    })
                    
                    # Cập nhật last checkpoint
                    checkpoints = msg.get('checkpoints') or []
                    if checkpoints:
                        last = checkpoints[-1]
                        cp_text = f"{_vi_status(last.get('tag') or last.get('status'), last.get('message'))} - {_polish_message(last.get('message'))}"
                        pick.tracking_last_checkpoint = cp_text
                    
                    _logger.info(f"Updated tracking for picking {pick.name}: {tracking_number} -> {tag}")
            
            # Tìm trong sale.order
            orders = SaleOrder.search([('tracking_number', '=', tracking_number)])
            if orders:
                for order in orders:
                    order.write({
                        'tracking_payload': msg,
                        'tracking_status': _vi_status(tag, tag),
                        'tracking_last_update': request.env['ir.fields'].Datetime.now(),
                    })
                    
                    # Cập nhật last checkpoint
                    checkpoints = msg.get('checkpoints') or []
                    if checkpoints:
                        last = checkpoints[-1]
                        cp_text = f"{_vi_status(last.get('tag') or last.get('status'), last.get('message'))} - {_polish_message(last.get('message'))}"
                        order.tracking_last_checkpoint = cp_text
                    
                    _logger.info(f"Updated tracking for order {order.name}: {tracking_number} -> {tag}")
            
            if not picks and not orders:
                _logger.warning(f"AfterShip webhook: No record found for tracking_number {tracking_number}")
                return {'status': 'warning', 'message': f'No record found for {tracking_number}'}
            
            return {'status': 'success', 'message': f'Updated {len(picks)} picking(s) and {len(orders)} order(s)'}
            
        except Exception as e:
            _logger.exception(f"AfterShip webhook error: {e}")
            return {'status': 'error', 'message': str(e)}
