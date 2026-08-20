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
