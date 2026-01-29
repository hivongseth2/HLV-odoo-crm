# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    has_bom_from_combo = fields.Boolean(
        string='Đã có BOM từ Combo',
        compute='_compute_has_bom_from_combo',
        help='Đánh dấu sản phẩm combo đã được chuyển đổi thành BOM'
    )

    @api.depends('is_combo', 'bom_ids')
    def _compute_has_bom_from_combo(self):
        for record in self:
            if record.is_combo and record.bom_ids:
                record.has_bom_from_combo = True
            else:
                record.has_bom_from_combo = False

    def action_open_combo_to_bom_wizard(self):
        """Mở wizard chuyển đổi Combo thành BOM"""
        self.ensure_one()
        if not self.is_combo:
            return {'type': 'ir.actions.act_window_close'}
        
        return {
            'name': _('Chuyển Combo thành BOM'),
            'type': 'ir.actions.act_window',
            'res_model': 'combo.to.bom.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_product_template_ids': [(6, 0, [self.id])],
            },
        }
