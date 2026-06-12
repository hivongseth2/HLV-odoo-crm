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

    package_transfer_qty = fields.Float(
        string="Package Transfer Quantity",
        default=0.0,
        digits='Product Unit of Measure',
        copy=False,
        help="Quantity selected to move while the full source package remains reserved.",
    )
    package_transfer_qty_set = fields.Boolean(
        string="Package Transfer Quantity Set",
        default=False,
        copy=False,
    )
