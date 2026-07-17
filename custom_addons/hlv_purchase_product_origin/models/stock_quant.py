from odoo import fields, models


class StockQuant(models.Model):
    _inherit = "stock.quant"

    origin_country_id = fields.Many2one(
        comodel_name="res.country",
        string="Xuất xứ",
        related="lot_id.origin_country_id",
        store=True,
        index=True,
    )
