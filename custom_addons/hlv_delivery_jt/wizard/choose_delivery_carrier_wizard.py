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
        res_context = dict(self._context)
        res_context.update({
            'active_id': self.picking_id.id,
            'active_model': 'stock.picking',
            'default_picking_id': self.picking_id.id,
        })
        if self.carrier_type == 'ghn':
            if hasattr(self.picking_id, 'action_create_ghn_order'):
                action = self.picking_id.with_context(res_context).action_create_ghn_order()
            else:
                from odoo.exceptions import UserError
                raise UserError("Module Giao Hàng Nhanh chưa được cài đặt!")
        else:
            action = self.picking_id.with_context(res_context).action_open_jt_wizard()
        
        # Ensure the returned action preserves the new context
        if isinstance(action, dict) and 'context' in action:
            new_context = dict(action['context'])
            new_context.update(res_context)
            action['context'] = new_context
        elif isinstance(action, dict):
            action['context'] = res_context
            
        return action
