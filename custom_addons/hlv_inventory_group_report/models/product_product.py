from odoo import fields, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    hlv_manual_avg_cost_enabled = fields.Boolean(
        string="HLV dùng giá vốn TB nhập tay",
        copy=False,
    )
    hlv_manual_avg_cost = fields.Float(
        string="HLV giá vốn TB nhập tay",
        digits="Product Price",
        copy=False,
    )
