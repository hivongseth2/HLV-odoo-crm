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
    current_price = fields.Float(string='Giá hiện tại', readonly=True)
    new_price = fields.Float(string='Giá mới', required=True)

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
                # Find BOM Qty
                relevant_line = self.env['mrp.bom.line'].search([
                    ('bom_id.product_tmpl_id', '=', combo.id),
                    ('product_id', 'in', variants.ids)
                ], limit=1)
                qty = relevant_line.product_qty if relevant_line else 1.0
                
                combo_price = combo.x_studio_ga_web or combo.list_price

                lines.append((0, 0, {
                    'product_id': combo.id,
                    'current_status': combo.x_wp_stock_status,
                    'current_price': combo_price,
                    'new_price': combo_price, # Init same
                    'qty_in_combo': qty,
                    'to_update': True 
                }))
            
            res['line_ids'] = lines
            
        return res

    @api.onchange('new_price')
    def _onchange_new_price(self):
        """Update projected parent prices when child price changes"""
        if not self.current_price: return
        diff_unit = self.new_price - self.current_price
        for line in self.line_ids:
            line.new_price = line.current_price + (diff_unit * line.qty_in_combo)

    def action_confirm(self):
        self.ensure_one()
        
        _logger.error(f"[Wizard-DEBUG] Confirming Update. Product: {self.product_id.name}, Status: {self.new_status}, Price: {self.new_price}")
        
        parents_to_update = self.line_ids.filtered(lambda l: l.to_update).mapped('product_id')
        
        # 1. PRICE UPDATE (Standard Write)
        price_changed = self.new_price != self.current_price
        if price_changed:
            vals = {'x_studio_ga_web': self.new_price, 'list_price': self.new_price}
            self.product_id.write(vals)
            _logger.info(f"Updated Child Price to {self.new_price}")

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

        self.env.cr.commit() # FORCE PERSISTENCE
        
        # 3. VERIFICATION & SYNC
        
        # Invalidate cache for BOTH fields
        self.product_id.invalidate_recordset(['x_wp_stock_status', 'x_studio_ga_web', 'list_price'])
        parents_to_update.invalidate_recordset(['x_wp_stock_status', 'x_studio_ga_web', 'list_price'])
        
        # Manually trigger sync
        # Note: Price change triggers auto-sync via `write` override (for Child).
        # But for Parents, Price update is triggered via `_update_parent_combo_prices` (called by child write).
        # Stock update for parents needs manual trigger since we used SQL.
        
        # Trigger Sync for STOCK (Manual)
        _logger.error(f"[Wizard-DEBUG] Triggering manual stock sync...")
        
        # Child Sync (Manual Stock + Price Auto)
        # Price Auto Sync is queued by `write` above.
        # Stock Manual Sync:
        self.product_id._auto_sync_stock_to_wordpress(old_value=child_old_status, new_value=self.new_status)
        
        # Parents Sync
        for p in parents_to_update:
             old_val = parent_old_statuses.get(p.id)
             p._auto_sync_stock_to_wordpress(old_value=old_val, new_value=self.new_status)
             
             # Also Force Recompute Price for Parents (to be safe)
             if price_changed:
                 p._compute_combo_selling_price()

        # Log to Chatter
        msg_body = "<b>Cập nhật an toàn (Wizard):</b><ul>"
        if status_changed:
             msg_body += f"<li>Status: {self.new_status} (SQL Force)</li>"
        if price_changed:
             msg_body += f"<li>Price: {self.current_price:,.0f} -> {self.new_price:,.0f}</li>"
        msg_body += "</ul>"
        
        self.product_id.message_post(body=msg_body)
        
        for p in parents_to_update:
             p.message_post(body=f"Cập nhật theo linh kiện {self.product_id.name}:<br/>Status: {self.new_status} (Check DB: {p.x_wp_stock_status})")

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
    
    # Price Fields
    current_price = fields.Float(string='Giá cũ', readonly=True, force_save=True)
    new_price = fields.Float(string='Giá mới (Dự kiến)', readonly=True, force_save=True)
    qty_in_combo = fields.Float(string='SL trong Combo', readonly=True)
    
    to_update = fields.Boolean(string='Cập nhật', default=True)
