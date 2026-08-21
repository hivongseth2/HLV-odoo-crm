from odoo import fields, models


class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    # Máy in IoT Box gán riêng cho kho này — dùng để tự động in phiếu giao hàng
    # thẳng ra đúng máy in của kho khi sale bấm nút in trên trang /sale_plan,
    # không cần chọn máy in mỗi lần (xem services/delivery_planner_printing.py).
    x_iot_printer_device_id = fields.Many2one(
        'iot.device',
        string='Máy in IoT của kho',
        domain=[('type', '=', 'printer')],
        help='Máy in IoT Box được gán cho kho này. Khi in phiếu giao hàng cho đơn '
             'thuộc kho này, hệ thống sẽ tự chọn đúng máy in này thay vì phải chọn tay.',
    )
    x_iot_report_id = fields.Many2one(
        'ir.actions.report',
        string='Mẫu phiếu lấy hàng IoT của kho',
        domain=[('model', '=', 'stock.picking')],
        help='Report template dùng khi sale bấm in phiếu lấy hàng cho kho này qua IoT. '
             'Để trống thì dùng mẫu mặc định (tìm theo tên "Hoạt động lấy hàng TSN").',
    )
    x_iot_queue_limit = fields.Integer(
        string='Số đơn tối đa trong hàng chờ in',
        default=0,
        help='Số đơn TỐI ĐA đang xử lý (chưa hủy/chưa hoàn tất giao) mà kho này cho phép '
             'cùng lúc trong hàng chờ in IoT — sale sẽ không gửi được yêu cầu in mới nếu kho '
             'đã đủ số này. Để 0 = không giới hạn.',
    )
