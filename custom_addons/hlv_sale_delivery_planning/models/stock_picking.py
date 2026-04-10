from odoo import models, fields


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    x_printed = fields.Boolean(
        string='Đã in phiếu lấy hàng',
        default=False,
        copy=False,
        help='Đánh dấu tự động khi phiếu được in từ màn hình điều phối giao hàng',
    )
