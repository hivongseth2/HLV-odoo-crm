# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class WordPressConfig(models.Model):
    """
    WordPress/WooCommerce Configuration
    Lưu trữ thông tin kết nối đến WordPress store.
    Credentials được lưu trong System Parameters để bảo mật.
    """
    _name = 'wordpress.config'
    _description = 'WordPress Configuration'
    _rec_name = 'name'

    # ===========================================
    # FIELDS
    # ===========================================
    name = fields.Char(
        string='Tên cấu hình',
        required=True,
        help='Tên để nhận biết cấu hình (VD: Store chính)'
    )

    wc_domain = fields.Char(
        string='WordPress Domain',
        required=True,
        help='Domain của WordPress (VD: https://hoanglongvu.com - KHÔNG có dấu / cuối)'
    )

    # Credentials - computed fields lưu trong System Parameters
    wc_key = fields.Char(
        string='Consumer Key',
        compute='_compute_credentials',
        inverse='_inverse_wc_key',
        help='WooCommerce API Consumer Key'
    )

    wc_secret = fields.Char(
        string='Consumer Secret',
        compute='_compute_credentials',
        inverse='_inverse_wc_secret',
        help='WooCommerce API Consumer Secret'
    )

    # Optional settings
    cache_purge_url = fields.Char(
        string='Cache Purge URL',
        help='LiteSpeed cache purge endpoint (tùy chọn)',
        default='/wp-json/litespeed/v1/purge?type=product&sku='
    )

    sync_log_days = fields.Integer(
        string='Giữ log (ngày)',
        default=30,
        help='Số ngày giữ lại sync logs'
    )

    max_retry_attempts = fields.Integer(
        string='Số lần thử lại tối đa',
        default=3,
        help='Số lần thử lại khi gặp lỗi trước khi dừng hẳn'
    )

    retry_delay_seconds = fields.Integer(
        string='Thời gian chờ retry (giây)',
        default=30,
        help='Thời gian chờ giữa mỗi lần retry, tính theo giây. VD: 30 = chờ 30s, 60s, 90s... (tăng dần)'
    )

    no_retry_patterns = fields.Text(
        string='Mẫu lỗi không retry (mỗi dòng 1 pattern)',
        default='Không tìm thấy product trên WordPress\nProduct không có SKU',
        help='Mỗi dòng là 1 chuỗi con hoặc regex. Nếu lỗi khớp với bất kỳ dòng nào → không retry, đánh dấu failed ngay.'
    )

    batch_size = fields.Integer(
        string='Số lượng/Batch',
        default=50,
        help='Số lượng sản phẩm cập nhật trong 1 request (Max 100)'
    )

    sync_delay = fields.Float(
        string='Delay (giây)',
        default=1.0,
        help='Thời gian chờ giữa các lần gửi batch để tránh bị chặn'
    )

    # ===========================================
    # COMBO PRICING SETTINGS
    # ===========================================
    combo_pricing_method = fields.Selection([
        ('sum_combo_price', 'Cộng giá bán trong combo'),
        ('discount_percentage', 'Tổng giá giảm %'),
    ], string='Phương pháp tính giá combo',
       default='sum_combo_price',
       help='Chọn phương pháp tính giá bán cho sản phẩm combo (dựa trên BOM)')

    combo_discount_percentage = fields.Float(
        string='Phần trăm giảm giá combo (%)',
        default=0.0,
        help='Phần trăm giảm giá khi tính giá combo (VD: 10 = giảm 10%)'
    )

    # ===========================================
    # STOCK SYNC SETTINGS
    # ===========================================
    stock_status_field = fields.Selection([
        ('qty_available', 'Số lượng hiện có (qty_available)'),
        ('virtual_available', 'Số lượng dự kiến (virtual_available)'),
        ('free_qty', 'Số lượng khả dụng (free_qty)'),
    ], string='Trường xác định tình trạng kho',
       default='qty_available',
       help='Chọn trường để xác định sản phẩm còn hàng hay hết hàng')

    sync_stock_based_on_quantity = fields.Boolean(
        string='Đồng bộ dựa trên số lượng tồn',
        default=True,
        help='Nếu Tắt: Chỉ đồng bộ dựa trên "Tình trạng WP" thủ công. Nếu Bật: Kết hợp kiểm tra số lượng tồn kho.'
    )

    auto_sync_price = fields.Boolean(
        string='Tự động đồng bộ giá',
        default=False,
        help='Tự động đồng bộ giá lên WordPress khi giá sản phẩm thay đổi'
    )

    auto_sync_combo_stock = fields.Boolean(
        string='Tự động đồng bộ stock combo',
        default=False,
        help='Tự động cập nhật tình trạng kho của combo khi sản phẩm con thay đổi'
    )
    
    combo_stock_check_interval = fields.Integer(
        string='Chu kỳ kiểm tra (phút)',
        default=10,
        help='Thời gian giữa các lần quét stock combo (tối thiểu 1 phút)',
        inverse='_inverse_combo_cron_interval'
    )

    last_sync_date = fields.Datetime(
        string='Đồng bộ lần cuối',
        readonly=True
    )

    active = fields.Boolean(
        string='Hoạt động',
        default=True
    )

    # ===========================================
    # COMPUTE / INVERSE METHODS
    # ===========================================
    @api.depends('name')
    def _compute_credentials(self):
        """Lấy credentials từ System Parameters"""
        ICP = self.env['ir.config_parameter'].sudo()
        for record in self:
            if record.id:
                record.wc_key = ICP.get_param(f'wordpress_sync.config_{record.id}.wc_key', '')
                record.wc_secret = ICP.get_param(f'wordpress_sync.config_{record.id}.wc_secret', '')
            else:
                record.wc_key = ''
                record.wc_secret = ''

    def _inverse_wc_key(self):
        """Lưu wc_key vào System Parameters"""
        ICP = self.env['ir.config_parameter'].sudo()
        for record in self:
            if record.id and record.wc_key:
                ICP.set_param(f'wordpress_sync.config_{record.id}.wc_key', record.wc_key)

    def _inverse_wc_secret(self):
        """Lưu wc_secret vào System Parameters"""
        ICP = self.env['ir.config_parameter'].sudo()
        for record in self:
            if record.id and record.wc_secret:
                ICP.set_param(f'wordpress_sync.config_{record.id}.wc_secret', record.wc_secret)

    def _inverse_combo_cron_interval(self):
        """Cập nhật thời gian chạy cron khi thay đổi"""
        cron = self.env.ref('wordpress_sync.ir_cron_auto_check_combo_stock', raise_if_not_found=False)
        if cron:
            for record in self:
                if record.combo_stock_check_interval < 1:
                    record.combo_stock_check_interval = 1
                cron.sudo().write({'interval_number': record.combo_stock_check_interval})

    # ===========================================
    # CONSTRAINTS
    # ===========================================
    @api.constrains('wc_domain')
    def _check_domain(self):
        """Kiểm tra format domain"""
        for record in self:
            if record.wc_domain:
                if record.wc_domain.endswith('/'):
                    raise ValidationError('Domain KHÔNG được có dấu / cuối (VD: https://hoanglongvu.com)')
                if not record.wc_domain.startswith(('http://', 'https://')):
                    raise ValidationError('Domain phải bắt đầu bằng http:// hoặc https://')

    # ===========================================
    # PUBLIC METHODS
    # ===========================================
    def get_credentials(self):
        """
        Lấy credentials từ System Parameters
        Returns: tuple (wc_key, wc_secret)
        """
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        wc_key = ICP.get_param(f'wordpress_sync.config_{self.id}.wc_key', '')
        wc_secret = ICP.get_param(f'wordpress_sync.config_{self.id}.wc_secret', '')
        return wc_key, wc_secret

    def test_connection(self):
        """Test kết nối WordPress API"""
        self.ensure_one()

        wc_key, wc_secret = self.get_credentials()
        if not wc_key or not wc_secret:
            return self._notify('Thiếu Credentials', 'Vui lòng nhập Consumer Key và Secret', 'warning')

        try:
            import requests
            from requests.auth import HTTPBasicAuth

            url = f"{self.wc_domain}/wp-json/wc/v3/products?per_page=1"
            response = requests.get(
                url,
                auth=HTTPBasicAuth(wc_key, wc_secret),
                timeout=10
            )

            if response.status_code == 200:
                _logger.info(f"WordPress connection OK: {self.name}")
                return self._notify('Kết nối thành công', 'WordPress API hoạt động bình thường', 'success')
            else:
                error = f"HTTP {response.status_code}: {response.text[:100]}"
                _logger.error(f"WordPress connection failed: {error}")
                return self._notify('Kết nối thất bại', error, 'danger')

        except requests.exceptions.Timeout:
            return self._notify('Timeout', 'Không thể kết nối đến WordPress (timeout)', 'danger')
        except requests.exceptions.ConnectionError:
            return self._notify('Lỗi kết nối', 'Không thể kết nối đến server WordPress', 'danger')
        except Exception as e:
            _logger.exception(f"WordPress connection error: {e}")
            return self._notify('Lỗi', str(e), 'danger')

    # ===========================================
    # HELPER METHODS
    # ===========================================
    def _notify(self, title, message, notif_type='info'):
        """Hiển thị notification cho user"""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': notif_type,
                'sticky': False,
            }
        }
