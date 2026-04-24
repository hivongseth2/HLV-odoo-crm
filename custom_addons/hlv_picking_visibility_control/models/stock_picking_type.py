# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class StockPickingType(models.Model):
    _inherit = 'stock.picking.type'

    is_hidden_from_menu = fields.Boolean(
        string='Ẩn từ Menu chính',
        default=False,
        help='Nếu check, loại phiếu này sẽ bị ẩn khỏi menu chính. Chỉ hiển thị khi được gọi từ phiếu xuất kho'
    )
    is_delivery_note_type = fields.Boolean(
        string='Là loại phiếu bàn giao',
        default=False,
        help='Check nếu đây là loại phiếu bàn giao (BBGN, BBBG, v.v.)'
    )
