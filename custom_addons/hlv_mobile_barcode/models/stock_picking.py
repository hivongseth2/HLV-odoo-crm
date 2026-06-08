from odoo import models, fields

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    hlv_barcode_auto_cleared = fields.Boolean(
        string="Đã tự động xóa SL",
        default=False,
        copy=False,
        help="Cờ đánh dấu phiếu đã được tự động làm mới số lượng khi quét lần đầu tiên."
    )
