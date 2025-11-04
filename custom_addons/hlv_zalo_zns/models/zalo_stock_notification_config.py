# models/zalo_stock_notification_config.py
import logging
import requests
from datetime import datetime, timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ZaloStockNotificationConfig(models.Model):
    """
    Cấu hình Zalo OA để gửi thông báo tới nhân viên nội bộ
    khi có đơn hàng nhập/xuất kho
    
    === HƯỚNG DẪN SỬ DỤNG ===
    
    1. CÀI ĐẶT:
       - Vào Inventory > Configuration > Zalo Stock Notification
       - Tạo bản ghi mới với thông tin:
         + App ID: Lấy từ Zalo Developer Portal
         + Secret Key: Lấy từ Zalo Developer Portal
         + Refresh Token: Lấy từ OAuth flow của Zalo
         + Recipient User IDs: Nhập các Zalo User ID (mỗi ID một dòng)
           VD: 1228622149344688972
       - Chọn loại đơn cần gửi (Nhập/Xuất)
       - Đánh dấu Active
    
    2. ĐIỀU KIỆN GỬI THÔNG BÁO:
       - Đơn hàng đã validate (state = 'done')
       - Loại đơn: incoming (nhập) hoặc outgoing (xuất)
       - Kho phải là TSN hoặc TSNSR (kiểm tra warehouse_id.code)
       - Chưa gửi thông báo trước đó (zalo_stock_notification_sent = False)
    
    3. NỘI DUNG THÔNG BÁO:
       - Mã đơn hàng gốc (origin)
       - Trạng thái: Xuất/Nhập toàn bộ hay 1 phần
       - Thời gian xuất/nhập
       - Thông tin đối tác (tên, địa chỉ, SĐT)
       - Danh sách sản phẩm và số lượng
    
    4. TOKEN MANAGEMENT:
       - Access token tự động refresh khi hết hạn
       - Cron job chạy mỗi giờ để refresh token
       - Có thể refresh thủ công bằng button "Refresh Token"
    
    5. TEST:
       - Sau khi cấu hình, click "Test Gửi Tin Nhắn"
       - Kiểm tra Recipient User IDs có nhận được tin không
       - Nếu OK, validate một đơn nhập/xuất kho TSN hoặc TSNSR để test thật
    
    6. DEBUG:
       - Xem logs: grep "Zalo" trong odoo log file
       - Check zalo_stock_notification_sent field trong stock.picking
       - Verify warehouse code: picking_type_id.warehouse_id.code
    """
    _name = 'hlv.zalo.stock.notification'
    _description = 'Zalo Stock Notification Config'

    name = fields.Char(default='Zalo Stock Notification', required=True)
    app_id = fields.Char('App ID', required=True, default='')
    secret_key = fields.Char('Secret Key', required=True, default='')
    refresh_token = fields.Text('Refresh Token', required=True)
    access_token = fields.Text('Access Token', readonly=True)
    token_expires_at = fields.Datetime('Token Expires At', readonly=True)
    
    # Danh sách user_id cần gửi thông báo (mỗi dòng một ID)
    recipient_ids = fields.Text(
        'Recipient User IDs',
        default='1228622149344688972',
        help='Danh sách Zalo User ID cần nhận thông báo, mỗi ID một dòng'
    )
    
    # Cấu hình gửi cho loại đơn nào
    send_on_incoming = fields.Boolean('Gửi khi nhập kho', default=True)
    send_on_outgoing = fields.Boolean('Gửi khi xuất kho', default=True)
    
    active = fields.Boolean('Active', default=True)

    @api.model
    def _get_active_config(self):
        """Lấy config đang active"""
        return self.search([('active', '=', True)], limit=1)

    def _is_token_expired(self):
        """Kiểm tra token đã hết hạn chưa"""
        self.ensure_one()
        if not self.token_expires_at:
            return True
        # Thêm buffer 60s để tránh token hết hạn giữa chừng
        return fields.Datetime.now() >= (self.token_expires_at - timedelta(seconds=60))

    def refresh_zalo_access_token(self):
        """
        Refresh access token từ Zalo OAuth v4
        Tương đương với refresh_zalo_token_if_needed() trong PHP
        
        === CÁCH LẤY REFRESH TOKEN ===
        
        1. Truy cập Zalo Developer Portal: https://developers.zalo.me/
        2. Chọn ứng dụng (App) của bạn
        3. Vào phần OAuth Settings
        4. Thực hiện OAuth flow để lấy authorization code
        5. Exchange code để lấy access_token và refresh_token
        6. Lưu refresh_token vào config này
        
        === AUTO REFRESH ===
        
        - Hệ thống tự động refresh khi access token hết hạn
        - Cron job chạy mỗi giờ để refresh token
        - Có thể refresh thủ công bằng button "Refresh Token" trên form
        
        === TROUBLESHOOTING ===
        
        Nếu refresh thất bại:
        - Kiểm tra App ID và Secret Key có đúng không
        - Kiểm tra Refresh Token còn hợp lệ không (có thể hết hạn sau 90 ngày)
        - Kiểm tra OA còn active không
        - Xem logs để biết error code cụ thể
        """
        self.ensure_one()
        
        # Validate required fields
        if not self.refresh_token:
            raise UserError(_("Refresh token không được để trống"))
        if not self.app_id:
            raise UserError(_("App ID không được để trống"))
        if not self.secret_key:
            raise UserError(_("Secret Key không được để trống"))

        try:
            endpoint = 'https://oauth.zaloapp.com/v4/oa/access_token'
            
            headers = {
                'secret_key': self.secret_key,
                'Content-Type': 'application/x-www-form-urlencoded',
            }
            
            data = {
                'app_id': self.app_id,
                'grant_type': 'refresh_token',
                'refresh_token': self.refresh_token
            }
            
            _logger.info("Refreshing Zalo Stock Notification access token...")
            response = requests.post(endpoint, headers=headers, data=data, timeout=15)
            
            # Parse response first before checking status
            try:
                result = response.json()
            except ValueError as e:
                _logger.error("Invalid JSON response from Zalo API: %s", response.text[:200])
                raise UserError(_("Zalo API trả về dữ liệu không hợp lệ"))
            
            # Check for HTTP errors
            if response.status_code != 200:
                error_msg = result.get('error_description', result.get('message', 'Unknown error'))
                _logger.error("Zalo API HTTP %s: %s", response.status_code, error_msg)
                raise UserError(_("Lỗi Zalo API (HTTP %s): %s") % (response.status_code, error_msg))
            
            if result.get('access_token'):
                new_access_token = result['access_token']
                new_refresh_token = result.get('refresh_token', self.refresh_token)
                expires_in = int(result.get('expires_in', 3600))
                
                self.write({
                    'access_token': new_access_token,
                    'refresh_token': new_refresh_token,
                    'token_expires_at': fields.Datetime.now() + timedelta(seconds=expires_in)
                })
                
                _logger.info("Zalo Stock Notification access token refreshed successfully (expires_in=%s)", expires_in)
                return new_access_token
            else:
                error_msg = result.get('error_description', result.get('message', 'Unknown error'))
                _logger.error("Zalo Stock Notification token refresh failed: %s", error_msg)
                raise UserError(_("Không thể refresh Zalo token: %s") % error_msg)
                
        except requests.exceptions.RequestException as e:
            _logger.exception("Zalo Stock Notification token refresh request failed: %s", e)
            raise UserError(_("Lỗi kết nối Zalo API: %s") % str(e))
        except UserError:
            # Re-raise UserError as-is
            raise
        except Exception as e:
            _logger.exception("Unexpected error refreshing Zalo token: %s", e)
            raise UserError(_("Lỗi không mong muốn: %s") % str(e))

    def get_valid_access_token(self):
        """
        Lấy access token hợp lệ, tự động refresh nếu cần
        """
        self.ensure_one()
        
        if not self.access_token or self._is_token_expired():
            return self.refresh_zalo_access_token()
        
        return self.access_token

    def send_notification_message(self, user_id, message_text):
        """
        Gửi tin nhắn thông báo tới một user_id cụ thể
        
        :param user_id: Zalo User ID
        :param message_text: Nội dung tin nhắn
        :return: Response dict từ Zalo API
        """
        self.ensure_one()
        
        access_token = self.get_valid_access_token()
        
        if not access_token:
            _logger.error("Cannot send notification message: no valid access token")
            return {'error': 'No access token'}
        
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
            _logger.info("Sending Zalo Stock Notification message to user_id=%s", user_id)
            response = requests.post(endpoint, headers=headers, json=payload, timeout=15)
            result = response.json()
            
            if response.status_code == 200 and result.get('error') == 0:
                _logger.info("Zalo Stock Notification message sent successfully to %s", user_id)
            else:
                error_msg = result.get('message', 'Unknown error')
                _logger.warning("Zalo Stock Notification message failed: error=%s, message=%s", 
                              result.get('error'), error_msg)
            
            return result
            
        except Exception as e:
            _logger.exception("Failed to send Zalo Stock Notification message to %s: %s", user_id, e)
            return {'error': str(e)}

    def get_recipient_list(self):
        """
        Lấy danh sách recipient IDs từ text field
        
        === CÁCH LẤY ZALO USER ID ===
        
        User ID là mã định danh của user đã follow Official Account (OA).
        
        Cách 1 - Qua API GetProfile:
        - Sau khi user follow OA, gọi API GetProfile
        - User ID sẽ có trong response
        
        Cách 2 - Qua Webhook:
        - Cấu hình webhook trong Zalo Developer Portal
        - Khi user tương tác (message, follow), webhook sẽ nhận được user_id
        
        Cách 3 - Qua Zalo OA Dashboard:
        - Một số dashboard có hiển thị user_id của followers
        
        Format User ID: 
        - Là chuỗi số, VD: 1228622149344688972
        - Nhập mỗi ID trên một dòng trong field recipient_ids
        
        Lưu ý:
        - User phải đã follow OA mới gửi được tin nhắn
        - Nếu user chưa follow, API sẽ trả về lỗi
        """
        self.ensure_one()
        if not self.recipient_ids:
            return []
        
        # Split by line breaks và lọc các dòng trống
        ids = [line.strip() for line in self.recipient_ids.split('\n') if line.strip()]
        return ids

    def action_test_send_message(self):
        """
        Action button để test gửi tin nhắn
        """
        self.ensure_one()
        
        recipients = self.get_recipient_list()
        if not recipients:
            raise UserError(_("Chưa có recipient ID nào được cấu hình"))
        
        test_message = "🔔 Test tin nhắn từ Odoo HLV\n"
        test_message += f"Thời gian: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n"
        test_message += "Hệ thống thông báo đơn hàng nhập/xuất kho đang hoạt động bình thường."
        
        success_count = 0
        for user_id in recipients:
            result = self.send_notification_message(user_id, test_message)
            if result.get('error') == 0:
                success_count += 1
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Gửi tin nhắn test'),
                'message': _('Đã gửi thành công %s/%s tin nhắn') % (success_count, len(recipients)),
                'type': 'success' if success_count > 0 else 'warning',
                'sticky': False,
            }
        }

    def action_refresh_token(self):
        """
        Action button để manually refresh token
        """
        self.ensure_one()
        try:
            self.refresh_zalo_access_token()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Refresh Token'),
                    'message': _('Đã refresh access token thành công'),
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            raise UserError(_("Lỗi khi refresh token: %s") % str(e))
