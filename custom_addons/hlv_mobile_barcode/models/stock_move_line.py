from odoo import models, fields


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    qty_scanned = fields.Float(
        string="SL đã quét (Barcode)",
        default=0.0,
        digits='Product Unit of Measure',
        copy=False,
        help=(
            "Số lượng đã quét qua ứng dụng HLV Mobile Barcode. "
            "Field này chỉ dùng cho phiếu PICK. "
            "Không bị ảnh hưởng bởi các hành động assign/unreserve của Odoo. "
            "Khi xác nhận phiếu, giá trị này sẽ được ghi đè lên field 'quantity'."
        )
    )
