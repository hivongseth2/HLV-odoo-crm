# -*- coding: utf-8 -*-
from odoo import models, fields, _
from odoo.exceptions import UserError

class MilwaukeePriceSyncWizard(models.TransientModel):
    _name = 'milwaukee.price.sync.wizard'
    _description = 'Wizard đồng bộ giá Milwaukee'

    product_ids = fields.Many2many(
        'product.template', 
        string='Sản phẩm đã chọn'
    )
    
    sync_mode = fields.Selection([
        ('selected', 'Chỉ đồng bộ các sản phẩm đã chọn'),
        ('all', 'Đồng bộ toàn bộ sản phẩm đã map ID')
    ], string='Chế độ đồng bộ', default='selected', required=True)

    def default_get(self, fields_list):
        res = super(MilwaukeePriceSyncWizard, self).default_get(fields_list)
        active_ids = self._context.get('active_ids')
        if active_ids and self._context.get('active_model') == 'product.template':
            res['product_ids'] = [(6, 0, active_ids)]
        return res

    def action_sync(self):
        self.ensure_one()
        config = self.env['milwaukee.config'].search([('active', '=', True)], limit=1)
        
        if not config:
            raise UserError(_("Chưa cấu hình Milwaukee. Vui lòng thiết lập trong Inventory > Configuration."))
            
        if self.sync_mode == 'selected':
            if not self.product_ids:
                 raise UserError(_("Vui lòng chọn ít nhất 1 sản phẩm để đồng bộ."))
            # Use action_push_prices logic but pass our specific product_ids
            return config.with_context(active_ids=self.product_ids.ids).action_push_prices()
        else:
            # Sync All mapped
            return config.action_push_prices()
