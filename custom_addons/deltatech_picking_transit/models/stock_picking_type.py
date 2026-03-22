# models/stock_picking_type.py

from odoo import fields, models


class StockPickingType(models.Model):
    _inherit = "stock.picking.type"

    two_step_transfer_use = fields.Selection(
        [("reception", "Nhập kho"), ("delivery", "Xuất kho")], string="Sử dụng chuyển kho 2 bước"
    )
    auto_second_transfer = fields.Boolean(
        string="Tự động tạo phiếu bước 2",
        help="Nếu được chọn, hệ thống sẽ tự động tạo một phiếu chuyển thứ hai khi phiếu đầu tiên được xác nhận, liên hệ trên phiếu sẽ quyết định kho nhận cho bước 2.",
    )
