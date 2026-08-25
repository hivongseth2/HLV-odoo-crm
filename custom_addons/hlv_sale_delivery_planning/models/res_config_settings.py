from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    lock_pick_slip_requests = fields.Boolean(
        string='Khóa mở/gửi in phiếu lấy hàng (sale plan)',
        config_parameter='hlv_sale_delivery_planning.lock_pick_slip_requests',
        help='Khi bật, sale KHÔNG xem trước / gửi yêu cầu in phiếu lấy hàng được trên trang '
             'sale plan — dùng để khóa tạm tính năng in IoT trước khi chính thức vận hành.',
    )

    auto_print_pick_slip_when_full = fields.Boolean(
        string='Tự động gửi in phiếu lấy hàng khi đủ hàng',
        config_parameter='hlv_sale_delivery_planning.auto_print_pick_slip_when_full',
        help='Khi bật, ngay khi phiếu lấy hàng (PICK) giữ ĐỦ hàng cho TẤT CẢ sản phẩm (không '
             'phải chỉ 1 phần), hệ thống tự động gửi yêu cầu in vào hàng chờ theo kho — không '
             'cần sale bấm gửi in. Mỗi phiếu chỉ tự động gửi 1 lần. Vẫn tôn trọng khóa "Khóa '
             'mở/gửi in phiếu lấy hàng" ở trên nếu đang bật.',
    )

    restrict_pack_to_assigned_user = fields.Boolean(
        string='Chỉ người được assign mới được đóng gói',
        config_parameter='hlv_sale_delivery_planning.restrict_pack_to_assigned_user',
        help='Khi bật, chỉ người được assign lúc in phiếu lấy hàng hoặc quản lý kho mới được vào/validate phiếu PACK.',
    )

    pick_print_time_mode = fields.Selection(
        string='Chế độ ghi nhận thời gian in',
        selection=[
            ('first', 'Lần đầu in (chỉ ghi nhận một lần)'),
            ('latest', 'Lần in gần nhất (luôn cập nhật)'),
        ],
        default='first',
        config_parameter='hlv_sale_delivery_planning.pick_print_time_mode',
        help='Quyết định cách ghi nhận x_pick_print_start_at khi in phiếu lấy hàng nhiều lần.',
    )
    pick_print_time_mode = fields.Selection(
        selection=[
            ('first', 'Ghi nhận lần đầu in'),
            ('latest', 'Ghi nhận lần in gần nhất'),
        ],
        string='Chế độ ghi nhận thời gian in',
        config_parameter='hlv_sale_delivery_planning.pick_print_time_mode',
        default='first',
        help='first: chỉ ghi thời gian in lần đầu tiên (giữ nguyên nếu đã có). latest: luôn cập nhật với lần in mới nhất.',
    )
