# -*- coding: utf-8 -*-
from odoo import models, api, fields

class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _create_order_picking(self):
        res = super(PosOrder, self)._create_order_picking()
        for order in self:
            if order.picking_ids:
                for picking in order.picking_ids:
                    # Skip if already set
                    if picking.x_studio_pos_group:
                        continue
                        
                    # Determine date source: date_done > date_order > now
                    src_date = picking.date_done or order.date_order or fields.Datetime.now()
                    
                    # Convert to user timezone
                    try:
                        local_dt = fields.Datetime.context_timestamp(self, src_date)
                    except Exception:
                        local_dt = src_date
                        
                    # Format: POS/ddmmyy
                    group_name = local_dt.strftime("POS/%d%m%y")
                    picking.write({'x_studio_pos_group': group_name})
        return res
