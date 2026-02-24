# -*- coding: utf-8 -*-
from odoo import models, api, fields

class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _propagate_pos_fields_to_downstream(self, picking, group_name, payment_method_str):
        """
        Propagate x_studio_pos_group and x_studio_pos_payment_method
        from source picking to all downstream pickings (pack, out)
        via move_dest_ids chain.
        """
        visited = set()
        downstream_pickings = self.env['stock.picking']

        # Collect all downstream pickings via move chain
        moves_to_check = picking.move_ids
        while moves_to_check:
            dest_moves = moves_to_check.mapped('move_dest_ids')
            dest_pickings = dest_moves.mapped('picking_id') - picking
            new_pickings = dest_pickings.filtered(lambda p: p.id not in visited)
            if not new_pickings:
                break
            downstream_pickings |= new_pickings
            visited |= set(new_pickings.ids)
            moves_to_check = new_pickings.mapped('move_ids')

        # Write POS fields to downstream pickings
        for dp in downstream_pickings:
            vals = {}
            if group_name and dp.x_studio_pos_group != group_name:
                vals['x_studio_pos_group'] = group_name
            if payment_method_str and dp.x_studio_pos_payment_method != payment_method_str:
                vals['x_studio_pos_payment_method'] = payment_method_str
            if vals:
                dp.write(vals)

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
                
                # Propagate to downstream pickings (pack, out)
                self._propagate_pos_fields_to_downstream(picking, group_name, payment_method_str)

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
                        group_name = local_dt.strftime(f"{prefix}{wh_suffix}%d%m%y")
                        vals['x_studio_pos_group'] = group_name
                    else:
                        group_name = picking.x_studio_pos_group
                    
                    # Update payment method
                    if payment_method_str:
                        vals['x_studio_pos_payment_method'] = payment_method_str
                        
                    if vals:
                        picking.write(vals)
                    
                    # Propagate to downstream pickings (pack, out)
                    self._propagate_pos_fields_to_downstream(picking, group_name, payment_method_str)
        return res
