from odoo import fields, models

# Tile mặc định: OpenStreetMap. Không cần khoá API nên cài xong là bản đồ chạy được
# ngay. Đổi sang nhà cung cấp khác chỉ cần sửa hai ô cấu hình, không phải sửa code.
DEFAULT_TILE_URL = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
DEFAULT_TILE_ATTRIBUTION = '© OpenStreetMap contributors'


class ResCompany(models.Model):
    """Cấu hình kết nối vTracking, để ở cấp công ty.

    Không để ở ``ir.config_parameter``: mỗi pháp nhân có thể có tài khoản vTracking riêng,
    và khoá API nằm trong system parameter thì mọi user đọc được cấu hình đều thấy.
    """

    _inherit = 'res.company'

    vtracking_base_url = fields.Char(
        string='Địa chỉ máy chủ vTracking',
        default='https://171.229.16.202:8443',
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
        string='Timeout (giây)', default=20,
    )
    vtracking_retention_days = fields.Integer(
        string='Giữ lịch sử vị trí (ngày)', default=30,
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
