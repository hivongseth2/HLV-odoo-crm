import json
import logging
from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)

class ZaloSheetWebhook(http.Controller):

    @http.route('/hlv_zalo/webhook/sheet_append', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def receive_sheet_data(self, **kwargs):
        try:
            # 1. Đọc dữ liệu JSON
            try:
                data = json.loads(request.httprequest.data)
            except Exception:
                data = kwargs

            _logger.info("Webhook Zalo nhận dữ liệu: %s", data)

            # 2. Lấy thông tin cần thiết
            id_don_mua = data.get('id_don_mua', 'N/A')
            nv_yeu_cau = data.get('nv_yeu_cau', 'N/A')

            # 3. Soạn nội dung tin nhắn (Đã sửa theo yêu cầu mới)
            message_text = (
                f"📝 ĐƠN MUA HÀNG CẦN DUYỆT\n"
                f"- ID Đơn: {id_don_mua}\n"
                f"- NV Yêu cầu: {nv_yeu_cau}"
            )

            # 4. Tìm config và Gửi Zalo
            ConfigModel = request.env['hlv.zalo.stock.notification'].sudo()
            config = ConfigModel.search([('active', '=', True)], limit=1)

            results = []
            if config:
                recipient_ids = ['9076053104406687668', '8987516370203943162']
                for user_id in recipient_ids:
                    res = config.send_notification_message(user_id, message_text)
                    results.append({'user_id': user_id, 'result': res})
            else:
                _logger.warning("Không tìm thấy cấu hình Zalo Active")

            # 5. Trả về kết quả
            return request.make_response(
                json.dumps({
                    'status': 'success',
                    'message': 'OK',
                    'data': results
                }),
                headers=[('Content-Type', 'application/json')]
            )

        except Exception as e:
            _logger.exception("Lỗi Webhook Zalo")
            return request.make_response(
                json.dumps({'status': 'error', 'message': str(e)}),
                headers=[('Content-Type', 'application/json')],
                status=500
            )
            
            
    @http.route('/hlv_zalo/webhook/oa', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def receive_zalo_oa_event(self, **kwargs):
        try:
            # 1. Lấy dữ liệu raw body
            raw_data = request.httprequest.data
            
            # Lấy config đang Active (chế độ chạy riêng)
            ConfigModel = request.env['hlv.zalo.stock.notification'].sudo()
            config = ConfigModel.search([('active', '=', True)], limit=1)

            # 2. --- BẢO MẬT: KIỂM TRA CHỮ KÝ (SIGNATURE) ---
            oa_secret_key = config.oa_secret_key if config else False
            zalo_signature = request.httprequest.headers.get('X-Zalo-Signature')

            if oa_secret_key and zalo_signature:
                expected_mac = hmac.new(
                    oa_secret_key.encode('utf-8'),
                    raw_data,
                    hashlib.sha256
                ).hexdigest()
                
                received_mac = zalo_signature.replace("mac=", "").strip()

                if received_mac != expected_mac:
                    _logger.warning("⚠️ Webhook Signature Invalid!")
                    return Response("Forbidden: Invalid Signature", status=403)
            # -----------------------------------------------

            # 3. Parse JSON
            try:
                data = json.loads(raw_data)
            except Exception:
                return Response("Invalid JSON", status=400)

            event_name = data.get('event_name')
            sender = data.get('sender', {})
            user_id = sender.get('id')
            
            _logger.info("Zalo OA Event (Private Mode): %s | User: %s", event_name, user_id)

            # 4. Xử lý tin nhắn text
            if event_name == 'user_send_text':
                message_content = data.get('message', {}).get('text', '').strip()
                
                # Check ID nhanh
                if message_content.lower() in ['id', 'uid', 'check id']:
                    if config:
                        # Dùng hàm gửi tin có sẵn của Config đó
                        reply_msg = f"Mã User ID của bạn là:\n{user_id}"
                        config.send_notification_message(user_id, reply_msg)
                    else:
                        _logger.warning("Không tìm thấy Config Active để reply tin nhắn")

            return Response("OK", status=200)

        except Exception as e:
            _logger.exception("Lỗi xử lý Zalo OA Webhook: %s", e)
            return Response("Internal Server Error", status=500)