from odoo import fields, models


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    hlv_manual_cost_total_enabled = fields.Boolean(
        string="HLV dùng thành tiền giá vốn nhập tay",
        copy=False,
    )
    hlv_manual_cost_total = fields.Float(
        string="HLV thành tiền giá vốn nhập tay",
        digits="Product Price",
        copy=False,
    )
