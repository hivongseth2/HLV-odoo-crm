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

    line_ids = fields.One2many('wordpress.update.stock.wizard.line', 'wizard_id', string='Sản phẩm Combo ảnh hưởng')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self.env.context.get('active_id')
        if active_id and 'product_id' in fields_list:
            product = self.env['product.template'].browse(active_id)
            res['product_id'] = product.id
            res['current_status'] = product.x_wp_stock_status
            
            # Compute lines
            lines = []
            
            # Find variants
            variants = product.product_variant_ids
            # Find BOM lines
            bom_lines = self.env['mrp.bom.line'].search([('product_id', 'in', variants.ids)])
            # Find parent phantom BOMs
            parent_boms = bom_lines.mapped('bom_id').filtered(lambda b: b.type == 'phantom' and b.active)
            parent_combos = parent_boms.mapped('product_tmpl_id')
            
            for combo in parent_combos:
                lines.append((0, 0, {
                    'product_id': combo.id,
                    'current_status': combo.x_wp_stock_status,
                    'to_update': True # Default ticked
                }))
            
            res['line_ids'] = lines
            
        return res

    def action_confirm(self):
        self.ensure_one()
        
        _logger.error(f"[Wizard-DEBUG] Confirming Update. Product: {self.product_id.name}, New Status: {self.new_status}")
        
        parents_to_update = self.line_ids.filtered(lambda l: l.to_update).mapped('product_id')
        
        # 3. DIRECT SQL UPDATE (Nuclear Option against Reverts)
        # Update Parents
        if parents_to_update:
            _logger.error(f"[Wizard-SQL] Updating {len(parents_to_update)} parents to {self.new_status} via SQL")
            self.env.cr.execute(
                "UPDATE product_template SET x_wp_stock_status = %s WHERE id IN %s",
                (self.new_status, tuple(parents_to_update.ids))
            )
        
        # Update Child
        if self.product_id.x_wp_stock_status != self.new_status:
            _logger.error(f"[Wizard-SQL] Updating Child {self.product_id.id} to {self.new_status} via SQL")
            self.env.cr.execute(
                "UPDATE product_template SET x_wp_stock_status = %s WHERE id = %s",
                (self.new_status, self.product_id.id)
            )

        self.env.cr.commit() # FORCE PERSISTENCE
        
        # 4. Invalidate Cache & Trigger Sync Manually
        self.product_id.invalidate_recordset(['x_wp_stock_status'])
        parents_to_update.invalidate_recordset(['x_wp_stock_status'])
        
        # Manually trigger sync since SQL bypasses triggers
        _logger.error(f"[Wizard-DEBUG] Triggering manual sync for Child {self.product_id.id} and {len(parents_to_update)} Parents")
        self.product_id._auto_sync_stock_to_wordpress()
        parents_to_update._auto_sync_stock_to_wordpress()
        
        # Log message on parents with Verification
        for p in parents_to_update:
            start_msg = f"WordPress Stock Status cập nhật theo sản phẩm con {self.product_id.name} -> {self.new_status} (SQL Force)."
            verify_msg = f" (Kiểm tra lại DB: {p.x_wp_stock_status})"
            p.message_post(body=start_msg + verify_msg)

        return {'type': 'ir.actions.act_window_close'}


class WordPressUpdateStockWizardLine(models.TransientModel):
    _name = 'wordpress.update.stock.wizard.line'
    _description = 'Chi tiết cập nhật stock combo'

    wizard_id = fields.Many2one('wordpress.update.stock.wizard', string='Wizard')
    product_id = fields.Many2one('product.template', string='Sản phẩm Combo', readonly=True)
    current_status = fields.Selection([
        ('instock', 'Còn hàng'),
        ('outofstock', 'Hết hàng'),
        ('discontinued', 'Ngừng kinh doanh'),
    ], string='Trạng thái hiện tại', readonly=True)
    
    to_update = fields.Boolean(string='Cập nhật', default=True)
