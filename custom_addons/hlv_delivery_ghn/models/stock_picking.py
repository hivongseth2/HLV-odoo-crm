# -*- coding: utf-8 -*-
from odoo import models, api

class StockPicking(models.Model):
    _inherit = "stock.picking"

    def action_open_ghn_fee_wizard(self):
        self.ensure_one()
        
        # Calculate total weight (prioritizing variant weight, then template weight)
        total_weight = 0
        for move in self.move_ids_without_package:
            # In Odoo, product_id.weight usually falls back to template, 
            # but we'll follow user's instruction to be explicit.
            weight = move.product_id.weight
            if not weight and move.product_id.product_tmpl_id:
                weight = move.product_id.product_tmpl_id.weight
            
            total_weight += (weight or 0) * move.product_uom_qty

        total_weight = total_weight * 1000 # Convert KG to Grams
        if total_weight == 0:
            total_weight = 1000
            
        return {
            "name": "Tính cước GHN",
            "type": "ir.actions.act_window",
            "res_model": "ghn.fee.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_picking_id": self.id,
                "default_weight": int(total_weight),
            }
        }
