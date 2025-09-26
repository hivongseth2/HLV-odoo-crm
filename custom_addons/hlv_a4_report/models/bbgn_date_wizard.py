# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from datetime import date

class BbgnDateWizard(models.TransientModel):
    _name = 'bbgn.date.wizard'
    _description = 'Chọn ngày đơn đặt hàng cho BBGN'

    picking_id = fields.Many2one('stock.picking', required=True, string='Phiếu giao nhận')
    order_date = fields.Date(string='Ngày đơn đặt hàng', required=True, default=fields.Date.context_today)

    def action_print(self):
        self.ensure_one()
        # Định dạng dd/mm/YYYY để hiển thị đúng yêu cầu
        order_date_str = self.order_date.strftime('%d/%m/%Y') if self.order_date else ''
        # Gọi report và truyền ngày qua context
        action = self.env.ref('hlv_a4_report.bbgn_a4_khong_gia').report_action(
            self.picking_id,
            config=False
        )
        # Ép context kèm ngày đã chọn
        action['context'] = dict(self.env.context, bbgn_order_date=order_date_str)
        return action
