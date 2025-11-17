# -*- coding: utf-8 -*-
from odoo import api, fields, models


class StockMoveLinePartial(models.Model):
    _inherit = "stock.move.line"

    # Lưu tham chiếu tới move_line gốc (nếu là partial pack)
    original_move_line_id = fields.Many2one(
        "stock.move.line",
        string="Original Move Line",
        help="Nếu từ partial pack, tham chiếu đến move_line trong picking gốc"
    )
