# -*- coding: utf-8 -*-
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)

class WordPressUpdatePriceWizard(models.TransientModel):
    _name = 'wordpress.update.price.wizard'
    _description = 'Cập nhật giá an toàn'

    product_id = fields.Many2one('product.template', string='Sản phẩm', required=True, readonly=True)
    product_name = fields.Char(related='product_id.name', string='Tên sản phẩm')
    
    current_price = fields.Float(string='Giá hiện tại', readonly=True)
    new_price = fields.Float(string='Giá mới', required=True)
    
    line_ids = fields.One2many('wordpress.update.price.wizard.line', 'wizard_id', string='Sản phẩm Combo ảnh hưởng')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self.env.context.get('active_id')
        if active_id and 'product_id' in fields_list:
            product = self.env['product.template'].browse(active_id)
            res['product_id'] = product.id
            
            # Determine price field (prefer x_studio_ga_web as per bulk view)
            current_price = product.x_studio_ga_web or product.list_price
            res['current_price'] = current_price
            res['new_price'] = current_price
            
            # Compute lines
            lines = []
            variants = product.product_variant_ids
            bom_lines = self.env['mrp.bom.line'].search([('product_id', 'in', variants.ids)])
            parent_boms = bom_lines.mapped('bom_id').filtered(lambda b: b.type == 'phantom' and b.active)
            parent_combos = parent_boms.mapped('product_tmpl_id')
            
            for combo in parent_combos:
                # Calculate projected price
                # Simple approximation: Parent New = Parent Old + (Child New - Child Old) * Qty
                # We need to find the specific BOM line to get Qty
                
                # Find relevant BOM line
                relevant_line = self.env['mrp.bom.line'].search([
                    ('bom_id.product_tmpl_id', '=', combo.id),
                    ('product_id', 'in', variants.ids)
                ], limit=1)
                
                qty = relevant_line.product_qty if relevant_line else 1.0
                
                current_parent_price = combo.x_studio_ga_web or combo.list_price
                # We can't calculate exact new price here because standard default_get
                # doesn't know 'new_price' user input yet. 
                # So we just load current status. 
                # The 'new_price' logic for parents needs onchange?
                
                lines.append((0, 0, {
                    'product_id': combo.id,
                    'current_price': current_parent_price,
                    'new_price': current_parent_price, # Default to same, user/onchange will update
                    'qty_in_combo': qty,
                    'to_update': True
                }))
            
            res['line_ids'] = lines
            
        return res

    @api.onchange('new_price')
    def _onchange_new_price(self):
        """Update projected parent prices when child price changes"""
        if not self.current_price:
            return
            
        diff_unit = self.new_price - self.current_price
        
        for line in self.line_ids:
            # Projected Limit = Old + Diff * Qty
            line.new_price = line.current_price + (diff_unit * line.qty_in_combo)

    def action_confirm(self):
        self.ensure_one()
        
        _logger.info(f"[PriceWizard] Updating {self.product_id.name} to {self.new_price}")
        
        parents_to_update = self.line_ids.filtered(lambda l: l.to_update).mapped('product_id')
        
        # 1. Update Child Price
        # We update both list_price and x_studio_ga_web to be safe
        vals = {
            'x_studio_ga_web': self.new_price,
            'list_price': self.new_price
        }
        self.product_id.write(vals)
        
        # 2. Trigger Recomputation for Parents
        # The 'write' above MIGHT trigger `_update_parent_combo_prices` via automation (product_template.py line 154)
        # But we want to be sure and Log it.
        
        # Wait, if `write` trigger runs, it does `_update_parent_combo_prices` which recalculates.
        # So we don't need to manually calculate. 
        # But we need to Sync.
        
        self.env.cr.commit() # Force save
        
        # 3. Log Verification
        start_msg = f"Giá cập nhật qua Wizard: {self.current_price:,.0f} -> {self.new_price:,.0f}."
        self.product_id.message_post(body=start_msg)
        
        # Log on parents
        for line in self.line_ids:
            if line.to_update:
                p = line.product_id
                # Force recompute just in case trigger didn't catch (e.g. context issues)
                p._compute_combo_selling_price()
                p.invalidate_recordset(['x_studio_ga_web', 'list_price'])
                
                verify_price = p.x_studio_ga_web
                
                msg = f"Giá cập nhật theo linh kiện {self.product_id.name}: {line.current_price:,.0f} -> {verify_price:,.0f}"
                p.message_post(body=msg)
                
        return {'type': 'ir.actions.act_window_close'}


class WordPressUpdatePriceWizardLine(models.TransientModel):
    _name = 'wordpress.update.price.wizard.line'
    _description = 'Chi tiết cập nhật giá combo'

    wizard_id = fields.Many2one('wordpress.update.price.wizard', string='Wizard')
    product_id = fields.Many2one('product.template', string='Sản phẩm Combo', readonly=True)
    
    current_price = fields.Float(string='Giá cũ', readonly=True, force_save=True)
    new_price = fields.Float(string='Giá mới (Dự kiến)', readonly=True, force_save=True)
    qty_in_combo = fields.Float(string='SL trong Combo', readonly=True)
    
    to_update = fields.Boolean(string='Cập nhật', default=True)
