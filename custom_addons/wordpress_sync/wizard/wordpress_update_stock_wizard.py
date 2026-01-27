# -*- coding: utf-8 -*-
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)

class WordPressUpdateStockWizard(models.TransientModel):
    _name = 'wordpress.update.stock.wizard'
    _description = 'Cập nhật trạng thái kho WordPress'

    product_id = fields.Many2one('product.template', string='Sản phẩm', required=True, readonly=True)
    current_status = fields.Selection([
        ('instock', 'Còn hàng'),
        ('outofstock', 'Hết hàng'),
        ('discontinued', 'Ngừng kinh doanh'),
    ], string='Trạng thái hiện tại', readonly=True)
    
    new_status = fields.Selection([
        ('instock', 'Còn hàng'),
        ('outofstock', 'Hết hàng'),
        ('discontinued', 'Ngừng kinh doanh'),
    ], string='Trạng thái mới', required=True, default='outofstock')

    # Price Fields
    current_list_price = fields.Float(string='Giá bán lẻ hiện tại', readonly=True)
    new_list_price = fields.Float(string='Giá bán lẻ mới', required=True)
    
    current_web_price = fields.Float(string='Giá Web hiện tại', readonly=True)
    new_web_price = fields.Float(string='Giá Web mới', required=True)
    
    current_combo_price = fields.Float(string='Giá combo hiện tại', readonly=True)
    new_combo_price = fields.Float(string='Giá combo mới', required=True)
    
    current_listed_price = fields.Float(string='Giá niêm yết hiện tại', readonly=True)
    new_listed_price = fields.Float(string='Giá niêm yết mới', required=True)

    line_ids = fields.One2many('wordpress.update.stock.wizard.line', 'wizard_id', string='Sản phẩm Combo ảnh hưởng')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self.env.context.get('active_id')
        if active_id and 'product_id' in fields_list:
            product = self.env['product.template'].browse(active_id)
            res['product_id'] = product.id
            res['current_status'] = product.x_wp_stock_status
            
            # Price init
            res.update({
                'current_list_price': product.list_price,
                'new_list_price': product.list_price,
                'current_web_price': product.x_studio_ga_web,
                'new_web_price': product.x_studio_ga_web,
                'current_combo_price': product.x_wp_combo_price,
                'new_combo_price': product.x_wp_combo_price,
                'current_listed_price': product.x_studio_ga_hng_nim_yt,
                'new_listed_price': product.x_studio_ga_hng_nim_yt,
            })
            
            # Compute lines
            lines = []
            
            variants = product.product_variant_ids
            bom_lines = self.env['mrp.bom.line'].search([('product_id', 'in', variants.ids)])
            parent_boms = bom_lines.mapped('bom_id').filtered(lambda b: b.type == 'phantom' and b.active)
            parent_combos = parent_boms.mapped('product_tmpl_id')
            
            for combo in parent_combos:
                # Find BOM Qty
                relevant_line = self.env['mrp.bom.line'].search([
                    ('bom_id.product_tmpl_id', '=', combo.id),
                    ('product_id', 'in', variants.ids)
                ], limit=1)
                qty = relevant_line.product_qty if relevant_line else 1.0
                
                # Parent Prices
                # Parent Selling Price (computed_combo_selling_price or x_studio_ga_web)
                p_selling = combo.x_studio_ga_web or combo.list_price
                # Parent Listed Price
                p_listed = combo.x_studio_ga_hng_nim_yt
                # Parent List Price
                p_list = combo.list_price

                lines.append((0, 0, {
                    'product_id': combo.id,
                    'current_status': combo.x_wp_stock_status,
                    'current_parent_selling_price': p_selling,
                    'new_parent_selling_price': p_selling,
                    'current_parent_list_price': p_list,
                    'new_parent_list_price': p_list,
                    'current_parent_listed_price': p_listed,
                    'new_parent_listed_price': p_listed,
                    'qty_in_combo': qty,
                    'to_update': True 
                }))
            
            res['line_ids'] = lines
            
        return res

    @api.onchange('new_combo_price', 'new_web_price', 'new_listed_price', 'new_status')
    def _onchange_prices(self):
        """Update projected parent prices and status with Fallback Logic"""
        
        # 0. Status Projection (Wizard forces parents to same status)
        for line in self.line_ids:
            line.new_status = self.new_status

        # 1. Selling Price Projection (Sum of Components)
        # Logic: If Combo Price > 0, use it. Else use Web Price.
        
        effective_old = self.current_combo_price if self.current_combo_price else self.current_web_price
        effective_new = self.new_combo_price if self.new_combo_price else self.new_web_price
        
        diff_selling = effective_new - effective_old
        
        if diff_selling != 0:
            for line in self.line_ids:
                line.new_parent_selling_price = line.current_parent_selling_price + (diff_selling * line.qty_in_combo)
        else:
             # Reset if no change
             for line in self.line_ids:
                line.new_parent_selling_price = line.current_parent_selling_price

        # 2. List Price Change -> Parent List Price (Always Sum)
        if self.current_list_price is not False:
            diff_list = self.new_list_price - self.current_list_price
            for line in self.line_ids:
                line.new_parent_list_price = line.current_parent_list_price + (diff_list * line.qty_in_combo)

        # 3. Listed Price Change -> Parent Listed Price (Always Sum of Listed)
        # Note: Listed Price usually doesn't have "Combo Price" fallback logic, it's just Sum of Listed.
        if self.current_listed_price is not False:
            diff_listed = self.new_listed_price - self.current_listed_price
            for line in self.line_ids:
                line.new_parent_listed_price = line.current_parent_listed_price + (diff_listed * line.qty_in_combo)

    def action_confirm(self):
        self.ensure_one()
        
        _logger.error(f"[Wizard-DEBUG] Confirming Update. Product: {self.product_id.name}, Status: {self.new_status}")
        
        parents_to_update = self.line_ids.filtered(lambda l: l.to_update).mapped('product_id')
        
        # 1. PRICE UPDATE
        vals = {}
        if self.new_list_price != self.current_list_price:
            vals['list_price'] = self.new_list_price
        
        if self.new_web_price != self.current_web_price:
             vals['x_studio_ga_web'] = self.new_web_price
            
        if self.new_combo_price != self.current_combo_price:
            vals['x_wp_combo_price'] = self.new_combo_price
            
        if self.new_listed_price != self.current_listed_price:
            vals['x_studio_ga_hng_nim_yt'] = self.new_listed_price

        if vals:
            self.product_id.write(vals)
            _logger.info(f"Updated Child Prices: {vals}")

        # 2. STOCK UPDATE (SQL Force)
        status_changed = self.product_id.x_wp_stock_status != self.new_status
        
        # Capture Old Values for Logging (Status)
        parent_old_statuses = {p.id: p.x_wp_stock_status for p in parents_to_update}
        child_old_status = self.product_id.x_wp_stock_status

        if parents_to_update:
            _logger.error(f"[Wizard-SQL] Updating {len(parents_to_update)} parents to {self.new_status} via SQL")
            self.env.cr.execute(
                "UPDATE product_template SET x_wp_stock_status = %s WHERE id IN %s",
                (self.new_status, tuple(parents_to_update.ids))
            )
        
        if status_changed:
            _logger.error(f"[Wizard-SQL] Updating Child {self.product_id.id} to {self.new_status} via SQL")
            self.env.cr.execute(
                "UPDATE product_template SET x_wp_stock_status = %s WHERE id = %s",
                (self.new_status, self.product_id.id)
            )

        self.env.cr.commit() 
        
        # 3. VERIFICATION & SYNC
        
        # Invalidate cache
        self.product_id.invalidate_recordset(['x_wp_stock_status', 'x_studio_ga_web', 'list_price', 'x_wp_combo_price', 'x_studio_ga_hng_nim_yt'])
        parents_to_update.invalidate_recordset(['x_wp_stock_status', 'x_studio_ga_web', 'list_price', 'x_studio_ga_hng_nim_yt'])
        
        # Trigger Sync for STOCK (Manual)
        _logger.error(f"[Wizard-DEBUG] Triggering manual stock sync...")
        
        self.product_id._auto_sync_stock_to_wordpress(old_value=child_old_status, new_value=self.new_status)
        
        # Parents Sync
        for p in parents_to_update:
             old_val = parent_old_statuses.get(p.id)
             p._auto_sync_stock_to_wordpress(old_value=old_val, new_value=self.new_status)
             
             # Force Recompute Price for Parents
             if vals:
                 p._compute_combo_selling_price()

        # Log to Chatter
        msg_body = "<b>Cập nhật an toàn (Wizard):</b><ul>"
        if status_changed:
             msg_body += f"<li>Status: {self.new_status} (SQL Force)</li>"
        if vals:
             msg_body += f"<li>Prices Updated: {vals}</li>"
        msg_body += "</ul>"
        
        self.product_id.message_post(body=msg_body)
        
        for p in parents_to_update:
             p.message_post(body=f"Cập nhật theo linh kiện {self.product_id.name}:<br/>Status: {self.new_status}")

        return {'type': 'ir.actions.act_window_close'}


class WordPressUpdateStockWizardLine(models.TransientModel):
    _name = 'wordpress.update.stock.wizard.line'
    _description = 'Chi tiết cập nhật stock combo'

    wizard_id = fields.Many2one('wordpress.update.stock.wizard', string='Wizard')
    product_id = fields.Many2one('product.template', string='Sản phẩm Combo')
    
    # Status Fields
    current_status = fields.Selection([
        ('instock', 'Còn hàng'),
        ('outofstock', 'Hết hàng'),
        ('discontinued', 'Ngừng kinh doanh'),
    ], string='Trạng thái hiện tại')
    
    new_status = fields.Selection([
        ('instock', 'Còn hàng'),
        ('outofstock', 'Hết hàng'),
        ('discontinued', 'Ngừng kinh doanh'),
    ], string='Trạng thái dự kiến')
    
    # Projected Parent Prices
    current_parent_selling_price = fields.Float(string='Giá bán cũ', readonly=True, force_save=True) # Web Price
    new_parent_selling_price = fields.Float(string='Giá bán mới', readonly=True, force_save=True)
    
    current_parent_list_price = fields.Float(string='Giá bán lẻ cũ', readonly=True, force_save=True)
    new_parent_list_price = fields.Float(string='Giá bán lẻ mới', readonly=True, force_save=True)
    
    current_parent_listed_price = fields.Float(string='Giá niêm yết cũ', readonly=True, force_save=True)
    new_parent_listed_price = fields.Float(string='Giá niêm yết mới', readonly=True, force_save=True)
    
    qty_in_combo = fields.Float(string='SL trong Combo', readonly=True)
    
    to_update = fields.Boolean(string='Cập nhật', default=True)
