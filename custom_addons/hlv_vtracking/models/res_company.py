from odoo import api, fields, models
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

    # --- Định mức tính kế hoạch ---------------------------------------------
    vtracking_avg_speed_kmh = fields.Float(
        string='Tốc độ trung bình (km/h)', default=35.0,
        help='Tính cả dừng đèn đỏ và kẹt xe, nên thấp hơn tốc độ đồng hồ. Sửa theo địa '
             'bàn: nội thành chậm hơn tuyến khu công nghiệp.',
    )
    vtracking_minutes_per_stop = fields.Integer(
        string='Thời gian mỗi điểm giao (phút)', default=10,
        help='Từ lúc tới nơi đến lúc rời đi: tìm chỗ đỗ, bốc hàng, ký nhận.',
    )
    vtracking_road_factor = fields.Float(
        string='Hệ số đường bộ', default=1.3,
        help='Quãng đường tính theo đường chim bay rồi nhân hệ số này. 1.3 nghĩa là đường '
             'thật dài hơn đường chim bay 30%. Đo lại bằng km GPS thực tế rồi chỉnh cho '
             'khớp địa bàn.',
    )

    # Tắt sẵn: bật là bắt đầu gọi Google Routes theo lượt, có tính tiền. Người quản trị
    # phải chủ động bật sau khi đã bật Routes API cho khoá trong Google Cloud Console —
    # mặc định bật sẽ thành hoá đơn bất ngờ cho công ty chỉ muốn dùng phần ước lượng.
    vtracking_road_route_enabled = fields.Boolean(
        string='Lấy lộ trình đường thật (Google Routes)', default=False,
        help='Bật thì hệ thống lấy đường đi thật của từng chuyến từ Google Routes: bản đồ '
             'vẽ nét liền theo đúng đường xe chạy và có thêm số km đường thật. Dùng CHUNG '
             'khoá với phần tra toạ độ, nhưng khoá đó phải được bật thêm Routes API. Tắt '
             'thì mọi thứ vẫn chạy bằng ước lượng đường chim bay như trước.',
    )

    vtracking_zone_match_km = fields.Float(
        string='Bán kính nhận cụm (km)', default=3.0,
        help='Địa chỉ cách điểm giao đã biết gần nhất trong khoảng này thì nhận luôn cụm '
             'của điểm đó; xa hơn vẫn đoán nhưng đánh dấu "chưa chắc" để người soát. Đo '
             'trên 86 ghim bản đồ: 3 km cho 100% đúng phần tự gán, nới lên 5 km thì tụt '
             'còn 96%.',
    )

    # --- Tra toạ độ ---------------------------------------------------------
    # Hai ô dưới đây đọc/ghi thẳng tham số hệ thống của `base_geolocalize`, KHÔNG tạo
    # tham số riêng: hai chỗ cùng giữ một khoá Google là kiểu lỗi mà người dùng đổi khoá
    # ở chỗ này rồi không hiểu vì sao chỗ kia vẫn hỏng. Hệ quả phải chấp nhận: giá trị áp
    # dụng TOÀN HỆ THỐNG, không riêng công ty đang mở.
    geocode_provider = fields.Selection(
        [('openstreetmap', 'OpenStreetMap (miễn phí, 1 lượt/giây)'),
         ('googlemap', 'Google Maps (cần khoá API, tính tiền theo lượt)')],
        string='Nhà cung cấp tra toạ độ',
        compute='_compute_geocode_settings', inverse='_inverse_geocode_provider',
        help='Áp dụng cho toàn hệ thống. Google tra tên doanh nghiệp tốt hơn hẳn, nên với '
             'địa chỉ khu công nghiệp thì nên dùng Google.',
    )
    geocode_google_key = fields.Char(
        string='Khoá API Google Maps',
        compute='_compute_geocode_settings', inverse='_inverse_geocode_google_key',
        help='Áp dụng cho toàn hệ thống (tham số base_geolocalize.google_map_api_key).',
    )

    @api.depends_context('uid')
    def _compute_geocode_settings(self):
        # Không phụ thuộc field nào của bản ghi — giá trị nằm ở tham số hệ thống.
        provider = self._geocode_provider_tech_name() or 'openstreetmap'
        key = self.env['ir.config_parameter'].sudo().get_param('base_geolocalize.google_map_api_key') or ''
        for company in self:
            company.geocode_provider = provider
            company.geocode_google_key = key

    def _inverse_geocode_provider(self):
        for company in self:
            self._set_geocode_provider(company.geocode_provider or 'openstreetmap')

    # ------------------------------------------------------------------
    # Tham số nhà cung cấp — lưu ID, không lưu tên
    # ------------------------------------------------------------------
    # ``base_geolocalize`` đọc tham số này bằng ``int(prov_id)`` rồi browse
    # ``base.geo_provider``, KHÔNG bắt lỗi. Lưu tên ('googlemap') vào đó thì mọi lần tra toạ
    # độ ném ValueError — bị nuốt ở tầng trên và hiện ra thành "máy không tìm được", nên
    # nhìn như Google trượt trong khi thật ra chưa gọi Google lần nào.
    @api.model
    def _geocode_provider_tech_name(self):
        """'googlemap' / 'openstreetmap' đang được chọn, '' nếu chưa chọn.

        Gặp giá trị dạng tên (do bản cũ của module này ghi) thì đổi luôn thành ID cho đúng
        cách ``base_geolocalize`` đọc — tự chữa, không cần người vào sửa tay.
        """
        raw = self.env['ir.config_parameter'].sudo().get_param('base_geolocalize.geo_provider')
        if not raw:
            return ''
        Provider = self.env['base.geo_provider'].sudo()
        if str(raw).isdigit():
            return Provider.browse(int(raw)).exists().tech_name or ''
        self._set_geocode_provider(str(raw))
        return str(raw)

    @api.model
    def _set_geocode_provider(self, tech_name):
        """Chọn nhà cung cấp theo tên kỹ thuật, ghi ĐÚNG dạng ID mà base_geolocalize cần."""
        provider = self.env['base.geo_provider'].sudo().search([('tech_name', '=', tech_name)], limit=1)
        if provider:
            self.env['ir.config_parameter'].sudo().set_param(
                'base_geolocalize.geo_provider', str(provider.id),
            )

    def _inverse_geocode_google_key(self):
        set_param = self.env['ir.config_parameter'].sudo().set_param
        for company in self:
            set_param('base_geolocalize.google_map_api_key', company.geocode_google_key or '')

    # Tài khoản mà máy chạy worker AI đăng nhập vào để giữ websocket. Yêu cầu mới được
    # đẩy qua kênh bus của chính tài khoản này — để trống thì AI không được gọi dậy, phiếu
    # nằm chờ cho tới khi có người bấm "Gửi lại".
    ai_worker_user_id = fields.Many2one(
        'res.users', string='Tài khoản worker AI',
        help='Tài khoản riêng cho máy chạy AI, chỉ cần quyền V-Tracking. Đừng dùng tài '
             'khoản của người: worker đăng nhập bằng mật khẩu lưu trên máy đó.',
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
