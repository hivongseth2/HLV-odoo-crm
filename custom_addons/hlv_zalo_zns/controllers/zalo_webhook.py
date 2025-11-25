from odoo import http, _
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)

class ZaloSheetWebhook(http.Controller):

    @http.route('/hlv_zalo/webhook/sheet_append', type='http', auth='public', methods=['POST'], csrf=False,cors='*')
    def receive_sheet_data(self, **kwargs):
        """
        API nhận dữ liệu từ Google Sheet và gửi Zalo
        URL gọi: https://domain-odoo-cua-ban.com/hlv_zalo/webhook/sheet_append
        """
        try:
            _logger.info("Received data from Google Sheet: %s", kwargs)

            # 1. Lấy dữ liệu từ Google Sheet gửi sang
            # Dữ liệu nằm trong kwargs
            id_don_mua = kwargs.get('id_don_mua', 'N/A')
            nv_yeu_cau = kwargs.get('nv_yeu_cau', 'N/A')
            don_dich = kwargs.get('don_dich', 'N/A')
            ngay_tao = kwargs.get('ngay_tao', '')

            # 2. Soạn nội dung tin nhắn
            message_text = (
                f"🔔 CÓ ĐƠN MUA MỚI TỪ SHEET\n\n"
                f"🔑 ID Đơn: {id_don_mua}\n"
                f"👤 NV Yêu cầu: {nv_yeu_cau}\n"
                f"📅 Ngày tạo: {ngay_tao}\n"
                f"🎯 Đơn đích: {don_dich}"
            )

            # 3. Lấy cấu hình Zalo đang Active
            # Gọi model hlv.zalo.stock.notification bạn đã cung cấp
            ConfigModel = request.env['hlv.zalo.stock.notification'].sudo()
            config = ConfigModel.search([('active', '=', True)], limit=1)

            if not config:
                return {'status': 'error', 'message': 'Không tìm thấy cấu hình Zalo Stock Notification active'}

            # 4. Danh sách người nhận cố định (Hardcode theo yêu cầu)
            recipient_ids = [
                '9076053104406687668',
                '8987516370203943162'
            ]

            results = []
            # 5. Gửi tin nhắn cho từng người
            for user_id in recipient_ids:
                # Gọi hàm send_notification_message có sẵn trong model của bạn
                res = config.send_notification_message(user_id, message_text)
                results.append({'user_id': user_id, 'result': res})

            return {
                'status': 'success', 
                'message': 'Đã xử lý gửi tin nhắn',
                'details': results
            }

        except Exception as e:
            _logger.exception("Lỗi xử lý webhook từ Sheet")
            return {'status': 'error', 'message': str(e)}