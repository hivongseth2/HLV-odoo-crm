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

    # --- Watchdog máy chủ kho (script chạy trên máy kho báo về, xem bin/iot_watchdog_windows.ps1) ---
    iot_watchdog_token = fields.Char(
        string='Token watchdog máy chủ kho',
        config_parameter='hlv_sale_delivery_planning.iot_watchdog_token',
        help='Chuỗi bí mật dùng chung giữa Odoo và script watchdog trên máy chủ kho '
             '(/api/iot_watchdog/heartbeat). ĐỂ TRỐNG = tắt hẳn tính năng nhận heartbeat. '
             'Đặt 1 chuỗi dài ngẫu nhiên, dán y hệt vào tham số -Token của script.',
    )
    iot_watchdog_max_silence_minutes = fields.Integer(
        string='Watchdog: số phút im lặng thì báo lỗi',
        config_parameter='hlv_sale_delivery_planning.iot_watchdog_max_silence_minutes',
        default=5,
        help='Quá số phút này không nhận được heartbeat từ máy chủ kho thì coi như máy đã '
             'tắt/mất mạng và gửi cảnh báo. Nên đặt gấp 2-3 lần chu kỳ chạy của script.',
    )
    iot_verify_grace_minutes = fields.Integer(
        string='Đối chiếu máy in: chờ bao nhiêu phút mới kết luận',
        config_parameter='hlv_sale_delivery_planning.iot_verify_grace_minutes',
        default=5,
        help='Sau khi Odoo gửi lệnh in, chờ số phút này rồi mới đối chiếu với số job máy in '
             'thật sự đã in. Phải LỚN HƠN chu kỳ chạy của script watchdog (mặc định 2 phút) để '
             'lệnh in có đủ thời gian in xong, tránh kết luận oan là "chưa in".',
    )
    iot_auto_requeue_unprinted = fields.Boolean(
        string='Tự động gửi lại lệnh in khi phát hiện chưa ra giấy',
        config_parameter='hlv_sale_delivery_planning.iot_auto_requeue_unprinted',
        help='Khi đối chiếu phát hiện phiếu đã gửi lệnh in nhưng máy in KHÔNG in ra giấy: bật = '
             'hệ thống tự đưa yêu cầu đó về hàng chờ để in lại ngay (có thể in trùng 1 tờ nếu '
             'đối chiếu sai); tắt = chỉ cảnh báo + hiện nhãn "NGHI CHƯA IN RA" để kho tự bấm '
             '"Gửi lại lệnh in". Dù bật hay tắt đều KHÔNG bao giờ im lặng bỏ qua.',
    )
    iot_alert_emails = fields.Char(
        string='Email nhận cảnh báo máy in IoT',
        config_parameter='hlv_sale_delivery_planning.iot_alert_emails',
        help='Danh sách email (phân tách bằng dấu phẩy) nhận cảnh báo khi service IoT của kho '
             'tắt, máy chủ kho mất kết nối, hoặc Odoo không kết nối được hộp IoT. Để trống thì '
             'chỉ cảnh báo trên dashboard (ai đang mở mới thấy).',
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
