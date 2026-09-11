from odoo import fields, models


class StockWarehouse(models.Model):
    """Cấu hình điều phối — mọi thứ đều theo KHO.

    Đặt ở đây chứ không đặt trong res.config.settings vì từng kho có quy tắc riêng
    (Bến Cam bật trước, các kho khác chưa). res.config.settings chỉ nên giữ giá trị
    mặc định khi tạo kho mới.
    """

    _inherit = 'stock.warehouse'

    x_dispatch_enabled = fields.Boolean(
        string='Bật điều phối chuyến', default=False, index=True,
    )
    x_dispatch_auto_accept = fields.Boolean(
        string='Tự nhận đăng ký', default=True,
        help='Tự nhận khi chuyến còn nhận đăng ký (đã công bố, chưa khoá, chưa quá hạn). '
             'Tắt thì mọi đăng ký đều chờ điều phối duyệt tay.',
    )
    x_dispatch_deadline_time = fields.Float(
        string='Giờ chốt đăng ký', default=15.0,
        help='Giờ trong ngày, dạng 15.5 = 15h30. Dùng khi không tính lùi từ giờ xe chạy.',
    )
    x_dispatch_deadline_offset_h = fields.Float(
        string='Chốt trước giờ chạy (giờ)', default=0.0,
        help='Khác 0 thì hạn đăng ký = giờ xuất phát trừ đi số giờ này, và bỏ qua "Giờ chốt '
             'đăng ký". Điều phối vẫn khoá chuyến tay được bất cứ lúc nào.',
    )
    x_dispatch_cross_sale_visible = fields.Boolean(
        string='Sale thấy điểm của sale khác', default=True,
        help='Tắt thì mỗi sale chỉ thấy điểm giao của khách mình, chuyến hiện thêm dòng '
             '"còn N điểm khác".',
    )
    x_dispatch_cross_sale_show_amount = fields.Boolean(
        string='Hiện giá trị đơn của sale khác', default=False,
    )
    x_dispatch_capacity_mode = fields.Selection(
        [('soft', 'Mềm — chỉ cảnh báo'), ('hard', 'Cứng — chặn vượt trần')],
        string='Kiểu trần điểm', default='soft', required=True,
    )
    x_dispatch_max_trips_per_day = fields.Integer(
        string='Số chuyến tối đa/ngày', default=4,
        help='Xe tải lớn chỉ dùng khi hàng dài vượt ngưỡng, và tài xế bỏ xe nhỏ sang lái tải '
             'nên số chuyến trong ngày giảm.',
    )

    zone_ids = fields.One2many('hlv.delivery.zone', 'warehouse_id', string='Cụm tuyến')
