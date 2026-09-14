from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    x_pickup_google_server_key = fields.Char(
        string='Google Maps API key (máy chủ)',
        config_parameter='hlv_purchase_pickup.google_server_key',
        help='Dùng để tra toạ độ và tính đường đi. Key này KHÔNG bao giờ được gửi xuống '
             'trình duyệt — khoá nó theo địa chỉ IP máy chủ trong Google Cloud Console.',
    )
    x_pickup_google_js_key = fields.Char(
        string='Google Maps API key (trình duyệt)',
        config_parameter='hlv_purchase_pickup.google_js_key',
        help='Dùng để vẽ bản đồ trên trang /pickup. Key này nằm trong mã nguồn trang nên '
             'chắc chắn lộ — bắt buộc khoá theo HTTP referrer, đó là cách bảo vệ duy nhất. '
             'Để trống thì trang vẫn chạy, chỉ là không có bản đồ.',
    )
    x_pickup_gps_far_meters = fields.Integer(
        string='Ngưỡng cảnh báo lệch GPS (m)',
        config_parameter='hlv_purchase_pickup.gps_far_meters',
        default=500,
        help='Bấm "đã tới" ở xa điểm quá ngưỡng này thì gắn cờ cho quản lý xem lại. Chỉ là '
             'cảnh báo, không chặn: GPS trong nhà xưởng lệch vài trăm mét là bình thường.',
    )
    x_pickup_max_optimize = fields.Integer(
        string='Số lần gọi Google tối đa mỗi chuyến',
        config_parameter='hlv_purchase_pickup.max_optimize_per_run',
        default=5,
        help='Trần để một chuyến bị bấm nghịch không đốt hết hạn mức của cả tháng.',
    )
    x_pickup_require_return = fields.Boolean(
        string='Bắt bấm "Đã về kho"',
        config_parameter='hlv_purchase_pickup.require_return',
        default=True,
        help='Bật thì trang /pickup hiện nút kết thúc chuyến khi về tới kho. Tắt thì chuyến '
             'coi như kết thúc ở điểm cuối — mất số liệu quãng về nhưng đỡ một thao tác.',
    )
