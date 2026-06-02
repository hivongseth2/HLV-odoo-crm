import json
import logging
from odoo import http, registry, SUPERUSER_ID, api
from odoo.http import request, Response
import threading  
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
            # 1. Lấy dữ liệu raw body
            raw_data = request.httprequest.data
            
            # Lấy config Zalo đang Active
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
            
            # Lấy thông tin tin nhắn và msg_id để check trùng
            message_obj = data.get('message', {})
            msg_id = message_obj.get('msg_id')
            # message_content = message_obj.get('text', '').strip()
            
            _logger.info("Zalo OA Event: %s | User: %s | MsgID: %s", event_name, user_id, msg_id)

            # === 4. CHỐNG TRÙNG LẶP (DEDUPLICATION) ===
            # Nếu Zalo gửi lại (Retry), msg_id sẽ giống hệt nhau.
            if msg_id:
                # Tìm xem message này đã được lưu trong lịch sử chưa
                is_duplicate = request.env['hlv.chatgpt.message'].sudo().search_count([
                    ('zalo_msg_id', '=', msg_id)
                ])
                
                if is_duplicate > 0:
                    _logger.info("🚫 BỎ QUA TIN NHẮN TRÙNG LẶP (MsgID: %s)", msg_id)
                    # Trả về 200 OK ngay để Zalo biết đã xử lý xong, không gửi lại nữa
                    return Response("OK", status=200)
                
            # =================================================
            message_content = ""
            image_url = False
            # 5. Xử lý tin nhắn text
            if event_name == 'user_send_text':
                message_content = message_obj.get('text', '').strip()
                logging.info("user send text message : %s", message_content)

            # Trường hợp B: Tin nhắn Ảnh (MỚI THÊM)
            elif event_name == 'user_send_image':
                attachments = message_obj.get('attachments', [])
                _logger.info(
                        "📸 FULL message_obj (IMAGE):\n%s",
                        json.dumps(message_obj, ensure_ascii=False, indent=2)
                    )
                _logger.info(
                        "📎 ATTACHMENTS RAW:\n%s",
                        json.dumps(attachments, ensure_ascii=False, indent=2)
                    )

                if attachments:
                    payload = attachments[0].get('payload', {})
                    image_url = payload.get('url') # Link ảnh
                    # Lấy mô tả ảnh (nếu user có nhập caption) hoặc gán mặc định
                    message_content = message_obj.get('text') or "Hãy phân tích hình ảnh này."
                    _logger.info("📸 User gửi ảnh: %s", image_url)
                    
                                
            
            elif event_name == 'user_send_link':
                attachments = message_obj.get('attachments', [])
                _logger.info(
                        "FULL message_obj (LINK):\n%s",
                        json.dumps(message_obj, ensure_ascii=False, indent=2)
                    )
                _logger.info(
                        "ATTACHMENTS RAW (LINK):\n%s",
                        json.dumps(attachments, ensure_ascii=False, indent=2)
                    )

                link_parts = []
                link_text = (message_obj.get('text') or '').strip()
                if link_text:
                    link_parts.append(link_text)

                for attachment in attachments:
                    payload = attachment.get('payload') or {}
                    title = payload.get('title') or payload.get('name')
                    url = payload.get('url') or payload.get('href')
                    description = payload.get('description') or payload.get('desc')
                    thumbnail = payload.get('thumbnail')

                    if title:
                        link_parts.append(f"Tiêu đề: {title}")
                    if url:
                        link_parts.append(f"Link: {url}")
                    if description:
                        link_parts.append(f"Mô tả: {description}")
                    if thumbnail:
                        link_parts.append(f"Thumbnail: {thumbnail}")

                message_content = "\n".join(link_parts).strip()
                if not message_content and attachments:
                    message_content = "Người dùng gửi link:\n%s" % json.dumps(
                        attachments,
                        ensure_ascii=False,
                        indent=2
                    )
                _logger.info("User gửi link: %s", message_content)

            # =============================================

            # === 6. XỬ LÝ LOGIC ===
            
            # --- CASE A: Tra cứu ID (Chỉ check nếu là text thuần) ---
            if event_name == 'user_send_text' and message_content.lower() in ['id', 'uid', 'check id']:
                if config:
                    config.send_notification_message(user_id, f"Mã User ID của bạn là:\n{user_id}")
            
            # --- CASE B: CHAT VỚI CHATGPT ---
            # Điều kiện: Có config, và (Có nội dung HOẶC Có ảnh)
            elif config and request.env['hlv.chatgpt.config'].sudo().search_count([('active', '=', True)]) > 0 and (message_content or image_url):
                
                _logger.info("🔄 Đã nhận tin/ảnh từ %s. Đang chuyển vào luồng xử lý ngầm...", user_id)

                # --- CHUẨN BỊ DỮ LIỆU CHO LUỒNG CON ---
                db_name = request.db
                
                # Hàm chạy ngầm (Background Task)
                def run_ai_background():
                    # Kết nối lại DB
                    db_registry = registry(db_name)
                    with db_registry.cursor() as new_cr:
                        env = api.Environment(new_cr, SUPERUSER_ID, {})
                        
                        try:
                            ChatSession = env['hlv.chatgpt.session']
                            ConfigModel = env['hlv.zalo.stock.notification']
                            thread_config = ConfigModel.search([('active', '=', True)], limit=1)
                            
                            # 1. Gọi AI xử lý (TRUYỀN THÊM image_url)
                            ai_reply = ChatSession.process_zalo_message(
                                user_id, 
                                message_content, 
                                zalo_msg_id=msg_id,
                                image_url=image_url  # <--- Quan trọng: Truyền link ảnh vào đây
                            )
                            
                            # 2. Gửi kết quả về Zalo
                            if ai_reply and thread_config:
                                thread_config.send_notification_message(user_id, ai_reply)
                                _logger.info("✅ Threading: Đã gửi tin nhắn AI xong cho %s", user_id)
                                
                        except Exception as e:
                            _logger.exception("❌ Lỗi trong luồng AI Background: %s", e)

                # --- KÍCH HOẠT LUỒNG CHẠY NGAY ---
                t = threading.Thread(target=run_ai_background)
                t.start()
            
            return Response("OK", status=200)

        except Exception as e:
            _logger.exception("Lỗi Webhook OA: %s", e)
            return Response("Internal Server Error", status=500)
