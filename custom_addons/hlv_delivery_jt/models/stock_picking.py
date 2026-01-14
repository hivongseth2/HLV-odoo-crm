# -*- coding: utf-8 -*-
from odoo import fields, models

class StockPicking(models.Model):
    _inherit = "stock.picking"

    jt_bill_code = fields.Char(string="J&T Bill Code", copy=False)
    jt_sort_line = fields.Char(string="J&T Sort Line", copy=False)
    jt_order_status = fields.Char(string="Trạng thái J&T", copy=False)
    jt_cod_fee = fields.Float(string="Phí COD J&T", copy=False)
    jt_insurance_fee = fields.Float(string="Phí bảo hiểm J&T", copy=False)
    jt_total_fee = fields.Float(string="Tổng phí J&T", copy=False)

    def action_open_jt_wizard(self):
        self.ensure_one()
        return {
            'name': 'Tạo đơn J&T Express',
            'type': 'ir.actions.act_window',
            'res_model': 'jt.create.order.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_picking_id': self.id}
        }
