# -*- coding: utf-8 -*-
from odoo import models, api

class StockPicking(models.Model):
    _inherit = "stock.picking"

    def action_open_ghn_fee_wizard(self):
        self.ensure_one()
        # Calculate total weight and dimensions
        total_weight = 0
        p_length = 0
        p_width = 0
        p_height = 0
        
        for move in self.move_ids_without_package:
            product = move.product_id
            total_weight += (product.weight or 0) * move.product_uom_qty
            
            # Aggregate dimensions (Sum height, max length/width)
            p_length = max(p_length, product.product_length or 0)
            p_width = max(p_width, product.product_width or 0)
            p_height += (product.product_height or 0) * move.product_uom_qty

        total_weight = total_weight * 1000 # Convert KG to Grams
        if total_weight == 0: total_weight = 1000
        if p_length == 0: p_length = 20
        if p_width == 0: p_width = 20
        if p_height == 0: p_height = 20
            
        return {
            "name": "Tính cước GHN",
            "type": "ir.actions.act_window",
            "res_model": "ghn.fee.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_picking_id": self.id,
                "default_weight": int(total_weight),
                "default_length": int(p_length),
                "default_width": int(p_width),
                "default_height": int(p_height),
            }
        }
