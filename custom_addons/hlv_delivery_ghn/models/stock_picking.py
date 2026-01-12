# -*- coding: utf-8 -*-
from odoo import models, api

class StockPicking(models.Model):
    _inherit = "stock.picking"

    def action_open_ghn_fee_wizard(self):
        self.ensure_one()
        
        # Simple heuristic for dimensions/weight
        # In a real scenario, this would sum up product weights
        total_weight = sum(self.move_line_ids.mapped(lambda ml: ml.product_id.weight * ml.quantity)) * 1000 # Convert to grams
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
