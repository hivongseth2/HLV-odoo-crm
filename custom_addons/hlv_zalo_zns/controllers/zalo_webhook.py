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