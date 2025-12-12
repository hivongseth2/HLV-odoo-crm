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
            nv_yeu_cau = data.get('nv_yeu_cau', '').strip() # Thêm .strip() để xóa khoảng trắng thừa nếu có

            # 3. Soạn nội dung tin nhắn
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
                # --- LOGIC MỚI BẮT ĐẦU TỪ ĐÂY ---
                
                # Danh sách nhân viên đặc biệt
                special_staffs = [
                    "ĐẶNG THỊ HỒNG HẠNH", 
                    "TRẦN HOÀNG PHI LONG", 
                    "DƯƠNG THỊ HÀ", 
                    "TRƯƠNG THÁI QUANG"
                ]

                # Kiểm tra xem nhân viên yêu cầu có nằm trong danh sách không
                # Sử dụng upper() để so sánh không phân biệt hoa thường cho chắc chắn
                if nv_yeu_cau.upper() in [name.upper() for name in special_staffs]:
                    # Nhóm này gửi cho user: 8987516370203943162
                    recipient_ids = ['8987516370203943162']
                else:
                    # Còn lại gửi cho user kia: 9076053104406687668
                    recipient_ids = ['9076053104406687668']
                
                # --- KẾT THÚC LOGIC MỚI ---

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
            # 1. Parse Data & Check Signature (GIỮ NGUYÊN CODE CŨ CỦA BẠN)
            raw_data = request.httprequest.data
            ConfigModel = request.env['hlv.zalo.stock.notification'].sudo()
            config = ConfigModel.search([('active', '=', True)], limit=1)

            # ... (Đoạn code check Signature giữ nguyên) ...
            oa_secret_key = config.oa_secret_key if config else False
            zalo_signature = request.httprequest.headers.get('X-Zalo-Signature')
            if oa_secret_key and zalo_signature:
                expected_mac = hmac.new(oa_secret_key.encode('utf-8'), raw_data, hashlib.sha256).hexdigest()
                received_mac = zalo_signature.replace("mac=", "").strip()
                if received_mac != expected_mac:
                    return Response("Forbidden", status=403)
            # -----------------------------------------------

            # 2. Parse JSON
            try:
                data = json.loads(raw_data)
            except Exception:
                return Response("Invalid JSON", status=400)

            event_name = data.get('event_name')
            sender = data.get('sender', {})
            user_id = sender.get('id')  # Zalo User ID

            # 3. XỬ LÝ SỰ KIỆN
            if event_name == 'user_send_text':
                message_content = data.get('message', {}).get('text', '').strip()
                
                # --- CASE A: Tra cứu ID (Giữ nguyên) ---
                if message_content.lower() in ['id', 'uid', 'check id']:
                    if config:
                        config.send_notification_message(user_id, f"ID của bạn: {user_id}")
                
                # --- CASE B: CHAT VỚI CHATGPT (MỚI) ---
                # Điều kiện: Có config Zalo, có bật ChatGPT, và nội dung không rỗng
                elif config and config.enable_chatgpt and message_content:
                    _logger.info("Zalo Webhook: Chuyển tin nhắn từ %s sang ChatGPT", user_id)
                    
                    # Gọi sang Model ChatGPT Session để xử lý
                    # Lưu ý: Dùng sudo() để bypass quyền truy cập nếu là public user
                    ChatSession = request.env['hlv.chatgpt.session'].sudo()
                    
                    try:
                        # 1. Gọi hàm xử lý (Lưu tin -> Hỏi AI -> Lưu tin)
                        ai_reply = ChatSession.process_zalo_message(user_id, message_content)
                        
                        # 2. Gửi câu trả lời về lại Zalo cho khách
                        if ai_reply:
                            config.send_notification_message(user_id, ai_reply)
                            
                    except Exception as e:
                        _logger.exception("Lỗi khi gọi ChatGPT từ Zalo Webhook: %s", e)
                        # Tùy chọn: Báo lỗi cho khách hoặc im lặng
                        config.send_notification_message(user_id, "Hệ thống AI đang bận, vui lòng thử lại sau.")

            return Response("OK", status=200)

        except Exception as e:
            _logger.exception("Lỗi Webhook OA: %s", e)
            return Response("Error", status=500)