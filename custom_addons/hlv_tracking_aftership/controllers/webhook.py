# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import logging
import hmac
import hashlib

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
    2. Đảm bảo 'aftership.webhook_secret' được cấu hình trong System Parameters (khuyến nghị để verify)
    """

    def _verify_webhook_signature(self, body_bytes, received_signature, secret):
        """
        Verify webhook signature from AfterShip
        AfterShip uses HMAC-SHA256 to sign the webhook payload
        """
        if not secret or not received_signature:
            return True  # Skip verification if not configured
        
        try:
            expected_signature = hmac.new(
                secret.encode('utf-8'),
                body_bytes,
                hashlib.sha256
            ).hexdigest()
            return hmac.compare_digest(expected_signature, received_signature)
        except Exception as e:
            _logger.error(f"Webhook signature verification error: {e}")
            return False

    @http.route('/aftership/webhook', type='json', auth='public', methods=['POST'], csrf=False)
    def aftership_webhook_handler(self, **post):
        """
        Nhận và xử lý webhook từ AfterShip
        
        Payload mẫu từ AfterShip:
        {
            "msg": {
                "id": "...",  # AfterShip tracking ID
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
            _logger.info(f"🔔 WEBHOOK_RECEIVED: {payload.get('event', 'update')}")
            
            # Verify webhook secret (recommended)
            webhook_secret = request.env['ir.config_parameter'].sudo().get_param('aftership.webhook_secret', '')
            if webhook_secret:
                received_signature = request.httprequest.headers.get('aftership-hmac-sha256', '')
                body_bytes = request.httprequest.get_data()
                
                if not self._verify_webhook_signature(body_bytes, received_signature, webhook_secret):
                    _logger.warning("⚠️ WEBHOOK_INVALID_SIGNATURE: Signature verification failed")
                    return {'status': 'error', 'message': 'Invalid signature'}
            
            # Lấy thông tin tracking từ payload
            msg = payload.get('msg', {})
            aftership_id = msg.get('id', '').strip()  # QUAN TRỌNG: AfterShip tracking ID
            tracking_number = msg.get('tracking_number', '').strip()
            slug = msg.get('slug', '').strip()
            tag = msg.get('tag') or msg.get('subtag') or msg.get('status')
            
            if not tracking_number:
                _logger.warning("⚠️ WEBHOOK_NO_TRACKING: No tracking_number in payload")
                return {'status': 'error', 'message': 'No tracking_number'}
            
            _logger.info(f"📦 WEBHOOK_DATA: tracking={tracking_number}, aftership_id={aftership_id[:8] if aftership_id else 'None'}, tag={tag}")
            
            # Tìm record trong database (stock.picking hoặc sale.order)
            Picking = request.env['stock.picking'].sudo()
            SaleOrder = request.env['sale.order'].sudo()
            
            updated_picks = 0
            updated_orders = 0
            
            # Tìm trong stock.picking
            # Ưu tiên tìm theo aftership_id (chính xác hơn), fallback về tracking_number
            picks = Picking.search([
                '|',
                ('aftership_id', '=', aftership_id),
                ('tracking_number', '=', tracking_number)
            ]) if aftership_id else Picking.search([('tracking_number', '=', tracking_number)])
            
            if picks:
                for pick in picks:
                    # Cập nhật dữ liệu tracking
                    pick.write({
                        'aftership_id': aftership_id,  # Cập nhật nếu chưa có
                        'tracking_slug': slug,
                        'tracking_payload': msg,
                        'tracking_status': _vi_status(tag, tag),
                        'tracking_last_update': request.env['ir.fields'].Datetime.now(),
                    })
                    
                    # Cập nhật last checkpoint
                    checkpoints = msg.get('checkpoints') or []
                    if checkpoints:
                        last = checkpoints[-1]
                        cp_msg = _polish_message(last.get('message', ''))
                        cp_status = _vi_status(last.get('tag') or last.get('status'), cp_msg)
                        cp_text = f"{cp_status} - {cp_msg}" if cp_msg else cp_status
                        pick.tracking_last_checkpoint = cp_text
                    
                    updated_picks += 1
                    _logger.info(f"✅ UPDATED_PICKING: {pick.name} -> {tag} ({len(checkpoints)} checkpoints)")
            
            # Tìm trong sale.order
            orders = SaleOrder.search([
                '|',
                ('aftership_id', '=', aftership_id),
                ('tracking_number', '=', tracking_number)
            ]) if aftership_id else SaleOrder.search([('tracking_number', '=', tracking_number)])
            
            if orders:
                for order in orders:
                    # Cập nhật dữ liệu tracking
                    order.write({
                        'aftership_id': aftership_id,  # Cập nhật nếu chưa có
                        'tracking_slug': slug,
                        'tracking_payload': msg,
                        'tracking_status': _vi_status(tag, tag),
                        'tracking_last_update': request.env['ir.fields'].Datetime.now(),
                    })
                    
                    # Cập nhật last checkpoint
                    checkpoints = msg.get('checkpoints') or []
                    if checkpoints:
                        last = checkpoints[-1]
                        cp_msg = _polish_message(last.get('message', ''))
                        cp_status = _vi_status(last.get('tag') or last.get('status'), cp_msg)
                        cp_text = f"{cp_status} - {cp_msg}" if cp_msg else cp_status
                        order.tracking_last_checkpoint = cp_text
                    
                    updated_orders += 1
                    _logger.info(f"✅ UPDATED_ORDER: {order.name} -> {tag} ({len(checkpoints)} checkpoints)")
            
            # Commit transaction để đảm bảo dữ liệu được lưu ngay
            request.env.cr.commit()
            
            if not picks and not orders:
                _logger.warning(f"⚠️ WEBHOOK_NOT_FOUND: No record found for tracking={tracking_number}, aftership_id={aftership_id[:8] if aftership_id else 'None'}")
                return {'status': 'warning', 'message': f'No record found for {tracking_number}'}
            
            _logger.info(f"🎉 WEBHOOK_SUCCESS: Updated {updated_picks} picking(s) and {updated_orders} order(s)")
            return {
                'status': 'success',
                'message': f'Updated {updated_picks} picking(s) and {updated_orders} order(s)',
                'updated_picks': updated_picks,
                'updated_orders': updated_orders
            }
            
        except Exception as e:
            _logger.exception(f"❌ WEBHOOK_ERROR: {e}")
            # Rollback nếu có lỗi
            request.env.cr.rollback()
            return {'status': 'error', 'message': str(e)}