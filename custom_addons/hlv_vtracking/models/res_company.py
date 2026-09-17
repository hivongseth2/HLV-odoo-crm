from odoo import fields, models
from odoo.exceptions import UserError

# Tile mặc định: OpenStreetMap. Không cần khoá API nên cài xong là bản đồ chạy được
# ngay. Đổi sang nhà cung cấp khác chỉ cần sửa hai ô cấu hình, không phải sửa code.
DEFAULT_TILE_URL = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
DEFAULT_TILE_ATTRIBUTION = '© OpenStreetMap contributors'
DEFAULT_BASE_URL = 'https://171.229.16.202:8443'
DEFAULT_TIMEOUT = 20
DEFAULT_RETENTION_DAYS = 30

# Giá trị điền cho công ty ĐÃ TỒN TẠI lúc cài module. `default=` của field chỉ áp dụng
# khi tạo bản ghi mới, nên nếu không có bước này thì mọi công ty có sẵn sẽ thấy ô rỗng
# và Timeout = 0 — và timeout 0 nghĩa là request không bao giờ chờ được.
INSTALL_DEFAULTS = {
    'vtracking_base_url': DEFAULT_BASE_URL,
    'vtracking_verify_ssl': True,
    'vtracking_timeout': DEFAULT_TIMEOUT,
    'vtracking_retention_days': DEFAULT_RETENTION_DAYS,
    'vtracking_map_tile_url': DEFAULT_TILE_URL,
    'vtracking_map_attribution': DEFAULT_TILE_ATTRIBUTION,
}


class ResCompany(models.Model):
    """Cấu hình kết nối vTracking, để ở cấp công ty.

    Không để ở ``ir.config_parameter``: mỗi pháp nhân có thể có tài khoản vTracking riêng,
    và khoá API nằm trong system parameter thì mọi user đọc được cấu hình đều thấy.
    """

    _inherit = 'res.company'

    vtracking_base_url = fields.Char(
        string='Địa chỉ máy chủ vTracking',
        default=DEFAULT_BASE_URL,
        help='Gốc host, không kèm đường dẫn. Đổi được vì nhà cung cấp đang dùng IP trần.',
    )
    vtracking_api_key = fields.Char(
        string='API key vTracking',
        help='Giá trị header APIKey do vTracking cấp.',
    )
    vtracking_verify_ssl = fields.Boolean(
        string='Kiểm tra chứng chỉ SSL', default=True,
        help='Máy chủ dùng IP trần nên chứng chỉ nhiều khả năng tự ký. Tắt là chấp nhận '
             'không xác thực được máy chủ — chỉ tắt khi đã hỏi vTracking mà chưa có tên miền.',
    )
    vtracking_expand_children = fields.Boolean(
        string='Lấy cả xe công ty con', default=False,
        help='Tương ứng tham số expand của API.',
    )
    vtracking_timeout = fields.Integer(
        string='Timeout (giây)', default=DEFAULT_TIMEOUT,
    )
    vtracking_retention_days = fields.Integer(
        string='Giữ lịch sử vị trí (ngày)', default=DEFAULT_RETENTION_DAYS,
        help='Một xe chạy cả ngày sinh hơn nghìn bản ghi. Để 0 là giữ vĩnh viễn — bảng sẽ '
             'phình rất nhanh, chỉ nên làm vậy khi có lý do rõ ràng.',
    )
    vtracking_map_tile_url = fields.Char(
        string='Nguồn tile bản đồ', default=DEFAULT_TILE_URL,
    )
    vtracking_map_attribution = fields.Char(
        string='Ghi công bản đồ', default=DEFAULT_TILE_ATTRIBUTION,
        help='Bắt buộc hiển thị theo điều khoản của hầu hết nhà cung cấp tile.',
    )

    # ------------------------------------------------------------------
    # Hành động
    # ------------------------------------------------------------------
    def action_open_vtracking_settings(self):
        """Mở cấu hình vTracking của công ty đang đăng nhập.

        Dùng ``res.company`` chứ KHÔNG dùng ``res.config.settings``: action của
        res.config.settings luôn được Odoo mở trong app Cài đặt và thay chỗ trang cài
        đặt gốc, nên bấm vào menu của module này lại làm mất màn hình Cài đặt chung.
        """
        company = self.env.company
        return {
            'type': 'ir.actions.act_window',
            'name': 'Kết nối vTracking — %s' % company.display_name,
            'res_model': 'res.company',
            'res_id': company.id,
            'view_mode': 'form',
            'views': [(self.env.ref('hlv_vtracking.view_res_company_vtracking_form').id, 'form')],
            'target': 'current',
        }

    def action_vtracking_test_connection(self):
        """Gọi thử một request nhỏ nhất và báo kết quả."""
        self.ensure_one()
        # Import tại chỗ: services kéo theo requests/pytz, không cần nạp khi Odoo khởi
        # động mà chỉ cần lúc thật sự gọi ra ngoài.
        from ..services.vtracking_client import VTrackingError
        from ..services.vtracking_sync import get_client

        try:
            result = get_client(self).ping()
        except VTrackingError as exc:
            raise UserError(str(exc)) from exc
        message = 'Kết nối được. vTracking báo có %s xe trong tài khoản.' % result['total']
        if result['sample_plate']:
            message += ' Ví dụ: %s.' % result['sample_plate']
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'vTracking',
                'message': message,
                'type': 'success',
                'sticky': False,
            },
        }
