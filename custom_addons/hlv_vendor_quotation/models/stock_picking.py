# -*- coding: utf-8 -*-
from odoo import models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _action_done(self):
        result = super()._action_done()
        # Kho xác nhận phiếu nhập từ NCC → đơn mua tự chuyển "Đã giao" trên trang NCC (NCC khỏi bấm).
        self.filtered(lambda p: p.picking_type_code == "incoming").purchase_id._hlv_mark_delivered_by_receipt()
        return result
