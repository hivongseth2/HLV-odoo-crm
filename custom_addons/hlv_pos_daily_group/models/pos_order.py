# -*- coding: utf-8 -*-
from odoo import models, api, fields

class PosOrder(models.Model):
    _inherit = 'pos.order'



    def action_update_pos_group_backfill(self):
        """
        Backfill/Update x_studio_pos_group for selected orders
        """
        for order in self:
            if not order.picking_ids:
                continue
                
            # Get unique payment method names
            payment_methods = list(set(order.payment_ids.mapped('payment_method_id.name')))
            payment_method_str = ", ".join(payment_methods) if payment_methods else ""
            
            for picking in order.picking_ids:
                vals = {}
                
                # Determine date source: date_done > date_order > now
                src_date = picking.date_done or order.date_order or fields.Datetime.now()
                
                # Convert to user timezone
                try:
                    local_dt = fields.Datetime.context_timestamp(self, src_date)
                except Exception:
                    local_dt = src_date
                    
                # Determine prefix based on payment method
                prefix = "POS"
                if len(payment_methods) == 1:
                    pm_name = payment_methods[0].lower()
                    if "tiền mặt" in pm_name:
                        prefix = "TM"
                    elif "chuyển khoản" in pm_name:
                        prefix = "CK"
                        
                # Determine warehouse suffix
                wh_suffix = "WH"
                wh = order.picking_type_id.warehouse_id
                if wh:
                    wh_val = (wh.code or wh.name or "").upper()
                    if wh_val in ["KBC", "BENCAM"]:
                        wh_suffix = "BC"
                    elif wh_val in ["TSN", "HCM"]:
                        wh_suffix = "HCM"
                        
                # Format: [Prefix][Warehouse][ddmmyy]
                # e.g. TMBC060226, CKHCM060226
                group_name = local_dt.strftime(f"{prefix}{wh_suffix}%d%m%y")
                
                # Always update if different (for backfill/fix purposes)
                if picking.x_studio_pos_group != group_name:
                    vals['x_studio_pos_group'] = group_name
                
                # Update payment method
                if payment_method_str and picking.x_studio_pos_payment_method != payment_method_str:
                    vals['x_studio_pos_payment_method'] = payment_method_str
                    
                if vals:
                    picking.write(vals)

    def _create_order_picking(self):
        res = super(PosOrder, self)._create_order_picking()
        for order in self:
            if order.picking_ids:
                # Reuse the logic from backfill action for consistency, 
                # but applied during creation (so self is the order being created)
                # We can call the backfill method on self as it iterates over self
                order.action_update_pos_group_backfill()
        return res
