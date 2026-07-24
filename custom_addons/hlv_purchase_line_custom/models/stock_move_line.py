from odoo import fields, models


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    stt = fields.Char(
        string="STT",
        related="move_id.stt",
        readonly=True,
    )
    production_year = fields.Char(
        string="Năm sản xuất",
        related="move_id.purchase_line_id.production_year",
        store=True,
        readonly=False,
    )
    country_of_origin = fields.Char(
        string="Xuất xứ",
        related="move_id.purchase_line_id.country_of_origin",
        store=True,
        readonly=False,
    )
    misa_purchase_order_org_ref_detail_id = fields.Char(
        string="MISA org_ref_detail_id",
        related="move_id.misa_purchase_order_org_ref_detail_id",
        readonly=True,
    )
