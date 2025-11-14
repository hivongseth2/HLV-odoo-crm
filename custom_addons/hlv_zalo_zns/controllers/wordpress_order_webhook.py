# -*- coding: utf-8 -*-
import logging
import json
from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class WordPressOrderWebhook(http.Controller):
    """
    Controller nhận thông tin đơn hàng từ WordPress và gửi thông báo Zalo
    
    === MỤC ĐÍCH ===
    - Nhận thông tin đơn hàng từ website WordPress
    - Sử dụng token manager của Odoo để gửi tin nhắn Zalo
    - Tránh xung đột token giữa WordPress và Odoo
    
    === ENDPOINT ===
    URL: https://your-odoo-domain.com/hlv_zalo/wordpress/order/notify
    Method: POST
    Content-Type: application/json
    
    === REQUEST BODY ===
    {
        "order_id": "12345",
        "customer_name": "Nguyễn Văn A",
        "customer_phone": "0123456789",
        "customer_email": "email@example.com",
        "customer_address": "123 Đường ABC, Quận XYZ, TP. HCM",
        "products": [
            {"name": "Sản phẩm A", "quantity": 2},
            {"name": "Sản phẩm B", "quantity": 1}
        ],
        "total": "500,000₫",
        "recipient_user_ids": ["user_id_1", "user_id_2"]  // Optional
    }
    
    === RESPONSE ===
    {
        "success": true,
        "message": "Đã gửi thông báo thành công",
        "sent_count": 2
    }
    
    hoặc
    
    {
        "success": false,
        "error": "No active Zalo token found"
    }
    
    === BẢO MẬT ===
    - Endpoint này là public (auth="public")
    - Nên thêm API key hoặc secret token để xác thực
    - Hoặc giới hạn IP được phép gọi
    """
    
    @http.route('/hlv_zalo/wordpress/order/notify', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def wordpress_order_notify(self, **kwargs):
        """
        Nhận thông tin đơn hàng từ WordPress và gửi thông báo Zalo
        
        :param kwargs: Dữ liệu đơn hàng từ WordPress
        :return: JSON response với kết quả
        """
        
        try:
            # Parse JSON data từ request body
            try:
                data = json.loads(request.httprequest.data.decode('utf-8'))
            except (json.JSONDecodeError, AttributeError, UnicodeDecodeError) as e:
                _logger.warning("WordPress webhook - Invalid JSON in request body: %s", str(e))
                return Response(
                    json.dumps({'success': False, 'error': 'Invalid JSON format'}),
                    content_type='application/json',
                    status=400
                )
            
            # Kiểm tra API key từ System Parameters
            api_key_param = request.env['ir.config_parameter'].sudo().get_param('odoo-secret-key')
            
            if api_key_param:
                # Lấy API key từ header
                request_api_key = request.httprequest.headers.get('X-API-Key')
                
                if not request_api_key:
                    _logger.warning("WordPress webhook - Missing API key in request header")
                    return Response(
                        json.dumps({'success': False, 'error': 'Missing API key. Please provide X-API-Key header.'}),
                        content_type='application/json',
                        status=401
                    )
                
                if request_api_key != api_key_param:
                    _logger.warning("WordPress webhook - Invalid API key provided")
                    return Response(
                        json.dumps({'success': False, 'error': 'Invalid API key'}),
                        content_type='application/json',
                        status=403
                    )
                
                _logger.debug("WordPress webhook - API key validated successfully")
            
            _logger.info("Received WordPress order webhook for order_id: %s", data.get('order_id', 'N/A'))
            
            # Validate required fields
            required_fields = ['order_id', 'customer_name', 'products', 'total']
            missing_fields = [field for field in required_fields if field not in data or not data[field]]
            
            if missing_fields:
                _logger.warning("WordPress webhook - Missing required fields: %s (order_id: %s)", 
                              missing_fields, data.get('order_id', 'N/A'))
                return Response(
                    json.dumps({'success': False, 'error': f'Missing required fields: {", ".join(missing_fields)}'}),
                    content_type='application/json',
                    status=400
                )
            
            # Lấy access token từ Shared Token Manager
            token_manager = request.env['hlv.zalo.shared.token'].sudo()
            access_token = token_manager._get_shared_token()
            
            if not access_token:
                _logger.error("WordPress webhook - No active Zalo token found (order_id: %s)", 
                            data.get('order_id', 'N/A'))
                return Response(
                    json.dumps({'success': False, 'error': 'No active Zalo token found. Please configure Zalo Shared Token Manager in Odoo.'}),
                    content_type='application/json',
                    status=500
                )
            
            # Lấy danh sách recipients (từ request hoặc từ config mặc định)
            recipient_user_ids = data.get('recipient_user_ids', [])
            
            # Nếu không có trong request, lấy từ config mặc định
            if not recipient_user_ids:
                stock_config = request.env['hlv.zalo.stock.notification'].sudo().search([('active', '=', True)], limit=1)
                if stock_config and stock_config.online_recipient_user_id:
                    # Mặc định gửi cho kế toán online (vì đơn từ web thường là online)
                    recipient_user_ids = [stock_config.online_recipient_user_id]
                    _logger.info("WordPress webhook - Using default recipient from config: %s (order_id: %s)", 
                               stock_config.online_recipient_user_id, data.get('order_id', 'N/A'))
                else:
                    _logger.warning("WordPress webhook - No recipients configured (order_id: %s)", 
                                  data.get('order_id', 'N/A'))
                    return Response(
                        json.dumps({'success': False, 'error': 'No recipients configured. Please add recipient_user_ids or configure Zalo Stock Notification in Odoo.'}),
                        content_type='application/json',
                        status=500
                    )
            else:
                _logger.info("WordPress webhook - Using %d recipients from request (order_id: %s)", 
                           len(recipient_user_ids), data.get('order_id', 'N/A'))
            
            # Tạo nội dung tin nhắn
            message = self._build_order_message(data)
            
            # Gửi tin nhắn cho từng recipient
            success_count = 0
            failed_count = 0
            results = []
            
            for user_id in recipient_user_ids:
                result = self._send_zalo_message(access_token, user_id, message)
                if result.get('error') == 0:
                    success_count += 1
                    _logger.info("WordPress webhook - Sent Zalo notification to %s successfully (order_id: %s)", 
                               user_id, data.get('order_id', 'N/A'))
                    results.append({'user_id': user_id, 'success': True})
                else:
                    failed_count += 1
                    error_msg = result.get('message', 'Unknown error')
                    _logger.warning("WordPress webhook - Failed to send Zalo notification to %s: %s (order_id: %s)", 
                                  user_id, error_msg, data.get('order_id', 'N/A'))
                    results.append({'user_id': user_id, 'success': False, 'error': error_msg})
            
            _logger.info("WordPress webhook - Summary for order_id %s: sent=%d, failed=%d", 
                       data.get('order_id', 'N/A'), success_count, failed_count)
            
            response_data = {
                'success': True,
                'message': 'Đã gửi thông báo thành công',
                'sent_count': success_count,
                'failed_count': failed_count,
                'results': results
            }
            
            return Response(
                json.dumps(response_data),
                content_type='application/json',
                status=200
            )
            
        except Exception as e:
            _logger.exception("Error processing WordPress order webhook: %s", e)
            return Response(
                json.dumps({'success': False, 'error': str(e)}),
                content_type='application/json',
                status=500
            )
    
    def _build_order_message(self, data):
        """
        Tạo nội dung tin nhắn từ dữ liệu đơn hàng
            
        :param data: Dict chứa thông tin đơn hàng
        :return: String message
        """

        # Lấy trạng thái & lý do hủy (nếu có)
        status = (data.get('order_status') or '').strip().lower()
        cancel_reason = (data.get('cancel_reason') or '').strip()

        # Header theo trạng thái đơn
        if status == 'cancelled':
            # === ĐƠN HỦY ===
            message = "🆘🆘🆘 HỦY ĐƠN HÀNG (hoanglongvu.com)\n"
            if cancel_reason:
                message += f"🔥LÝ DO: {cancel_reason}\n\n"
            else:
                message += "🔥LÝ DO: (không có ghi chú)\n\n"
        else:
            # === ĐƠN BÌNH THƯỜNG (MỚI / ĐANG XỬ LÝ / HOÀN THÀNH) ===
            message = "Đơn hàng mới (hoanglongvu.com)\n"

        # 👤 Khách hàng
        message += f"👤 Khách hàng: {data.get('customer_name', 'Không rõ')}\n"

        # 📦 Sản phẩm
        products = data.get('products', [])
        if products:
            message += "📦 Sản phẩm:\n"
            for product in products:
                name = product.get('name', 'Unknown')
                quantity = product.get('quantity', 0)
                message += f"• {name}    SL: {quantity}\n"

        # 🏠 Địa chỉ
        if data.get('customer_address'):
            message += f"🏠 Địa chỉ: {data['customer_address']}\n"

        # 📞 SĐT
        if data.get('customer_phone'):
            message += f"📞 SĐT: {data['customer_phone']}\n"

        # 📧 Email
        if data.get('customer_email'):
            message += f"📧 Email: {data['customer_email']}\n"

        # 💰 Tổng
        if data.get('total'):
            message += f"💰 Tổng: {data['total']}"

        return message

    
    def _send_zalo_message(self, access_token, user_id, message_text):
        """
        Gửi tin nhắn Zalo
        
        :param access_token: Zalo access token
        :param user_id: Zalo user ID
        :param message_text: Nội dung tin nhắn
        :return: Response dict từ Zalo API
        """
        import requests
        
        endpoint = 'https://openapi.zalo.me/v3.0/oa/message/cs'
        
        headers = {
            'Content-Type': 'application/json',
            'access_token': access_token
        }
        
        payload = {
            'recipient': {
                'user_id': user_id
            },
            'message': {
                'text': message_text
            }
        }
        
        try:
            response = requests.post(endpoint, headers=headers, json=payload, timeout=15)
            return response.json()
        except Exception as e:
            _logger.exception("Failed to send Zalo message: %s", e)
            return {'error': -1, 'message': str(e)}

