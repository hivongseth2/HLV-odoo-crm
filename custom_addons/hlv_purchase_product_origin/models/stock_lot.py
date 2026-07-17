from odoo import fields, models


class StockLot(models.Model):
    _inherit = "stock.lot"

    origin_country_id = fields.Many2one(
        comodel_name="res.country",
        string="Xuất xứ",
        index=True,
        copy=False,
        help="Quốc gia xuất xứ của hàng hóa trong lô/số sê-ri này.",
    )
