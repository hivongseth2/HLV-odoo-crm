# -*- coding: utf-8 -*-
from odoo import fields, models, api

class ChooseDeliveryCarrierWizard(models.TransientModel):
    _name = "choose.delivery.carrier.wizard"
    _description = "Choose Delivery Carrier Wizard"

    picking_id = fields.Many2one('stock.picking', string="Picking", required=True)
    carrier_type = fields.Selection([
        ('ghn', 'Giao Hàng Nhanh (GHN)'),
        ('jt', 'J&T Express')
    ], string="Đơn vị vận chuyển", default='ghn', required=True)

    def action_confirm_carrier(self):
        self.ensure_one()
        if self.carrier_type == 'ghn':
            return self.picking_id.action_create_ghn_order()
        else:
            return self.picking_id.action_open_jt_wizard()
