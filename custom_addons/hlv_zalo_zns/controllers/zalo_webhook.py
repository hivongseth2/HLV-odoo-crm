import json
from odoo import http, _
from odoo.http import request, Response # Nhớ import Response
import logging

_logger = logging.getLogger(__name__)

class ZaloSheetWebhook(http.Controller):

    @http.route('/hlv_zalo/webhook/sheet_append', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def receive_sheet_data(self, **kwargs):
        """
        API nhận dữ liệu từ Google Sheet (JSON raw body)
        """
        try:
            # --- BƯỚC 1: LẤY DỮ LIỆU JSON TỪ BODY REQUEST ---
            # Vì Google AppScript gửi JSON raw, ta không lấy từ kwargs mà lấy từ request.httprequest.data
            try:
                data = json.loads(request.httprequest.data)
            except Exception:
                # Fallback nếu gửi form-data thường
                data = kwargs

            _logger.info("Received data from Google Sheet: %s", data)

            # Lấy các trường dữ liệu (Lấy từ biến data vừa parse)
            # Lưu ý: Google Script gửi key nào thì lấy key đó (phân biệt hoa thường)
            id_don_mua = data.get('id_don_mua', 'N/A')
            nv_yeu_cau = data.get('nv_yeu_cau', 'N/A')
            don_dich = data.get('don_dich', 'N/A')
            ngay_tao = data.get('ngay_tao', '')

            # --- BƯỚC 2: SOẠN TIN NHẮN ---
            message_text = (
                f"🔔 CÓ ĐƠN MUA MỚI TỪ SHEET\n\n"
                f"🔑 ID Đơn: {id_don_mua}\n"
                f"👤 NV Yêu cầu: {nv_yeu_cau}\n"
                f"📅 Ngày tạo: {ngay_tao}\n"
                f"🎯 Đơn đích: {don_dich}"
            )

            # --- BƯỚC 3: TÌM CONFIG VÀ GỬI ---
            # Dùng sudo() để bỏ qua quyền truy cập nếu auth='public'
            ConfigModel = request.env['hlv.zalo.stock.notification'].sudo()
            config = ConfigModel.search([('active', '=', True)], limit=1)

            if not config:
                return self._response_json({'status': 'error', 'message': 'Không tìm thấy cấu hình Zalo Active'}, 404)

            recipient_ids = [
                '9076053104406687668',
                '8987516370203943162'
            ]

            results = []
            for user_id in recipient_ids:
                res = config.send_notification_message(user_id, message_text)
                results.append({'user_id': user_id, 'result': res})

            # --- BƯỚC 4: TRẢ VỀ JSON HỢP LỆ ---
            return self._response_json({
                'status': 'success',
                'message': 'Đã xử lý gửi tin nhắn',
                'details': results
            })

        except Exception as e:
            _logger.exception("Lỗi Webhook Zalo")
            return self._response_json({'status': 'error', 'message': str(e)}, 500)

    def _response_json(self, data, status=200):
        """Hàm hỗ trợ trả về JSON response chuẩn cho type='http'"""
        return request.make_response(
            json.dumps(data),
            headers=[('Content-Type', 'application/json')],
            status=status
        )