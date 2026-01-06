# -*- coding: utf-8 -*-
from odoo import models, api, fields

class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _create_order_picking(self):
        res = super(PosOrder, self)._create_order_picking()
        for order in self:
            if order.picking_ids:
                # Get unique payment method names
                payment_methods = list(set(order.payment_ids.mapped('payment_method_id.name')))
                payment_method_str = ", ".join(payment_methods) if payment_methods else ""
                
                for picking in order.picking_ids:
                    vals = {}
                    # Skip if already set or use format: POS/ddmmyy
                    if not picking.x_studio_pos_group:
                        # Determine date source: date_done > date_order > now
                        src_date = picking.date_done or order.date_order or fields.Datetime.now()
                        
                        # Convert to user timezone
                        try:
                            local_dt = fields.Datetime.context_timestamp(self, src_date)
                        except Exception:
                            local_dt = src_date
                            
                        # Format: POS/ddmmyy
                        group_name = local_dt.strftime("POS%d%m%y")
                        vals['x_studio_pos_group'] = group_name
                    
                    # Update payment method
                    if payment_method_str:
                        vals['x_pos_payment_method'] = payment_method_str
                        
                    if vals:
                        picking.write(vals)
        return res
