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
        
        _logger.info(f"[Wizard] Confirming Update. Product: {self.product_id.name}, New Status: {self.new_status}")
        
        # 1. Update Child Product
        if self.product_id.x_wp_stock_status != self.new_status:
            _logger.info(f"[Wizard] Updating Child {self.product_id.name} from {self.product_id.x_wp_stock_status} to {self.new_status}")
            self.product_id.write({'x_wp_stock_status': self.new_status})
        else:
            _logger.info(f"[Wizard] Child {self.product_id.name} already has status {self.new_status}")
        
        # 2. Update Selected Parent Combos
        parents_to_update = self.line_ids.filtered(lambda l: l.to_update).mapped('product_id')
        
        _logger.info(f"[Wizard] Found {len(parents_to_update)} parents to update: {parents_to_update.mapped('name')} (IDs: {parents_to_update.ids})")
        
        if parents_to_update:
            # Check current status of parents for debugging
            for p in parents_to_update:
                _logger.info(f"[Wizard] Parent {p.name} (ID: {p.id}) current: {p.x_wp_stock_status} -> new: {self.new_status}")
            
            parents_to_update.write({'x_wp_stock_status': self.new_status})
            
            # Verify update
            for p in parents_to_update:
                 _logger.info(f"[Wizard] Parent {p.name} (ID: {p.id}) AFTER WRITE: {p.x_wp_stock_status}")

            # Log message on parents
            for p in parents_to_update:
                p.message_post(body=f"WordPress Stock Status cập nhật theo sản phẩm con {self.product_id.name} -> {self.new_status}")

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
