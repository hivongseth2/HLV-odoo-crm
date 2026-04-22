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
        api_url = self.env['ir.config_parameter'].sudo().get_param('hlv_milwaukee_price_sync.api_url')
        if not api_url:
            raise UserError(_("Chưa cấu hình Milwaukee API URL. Vui lòng thiết lập trong Inventory > Configuration > Settings."))
            
        if self.sync_mode == 'selected':
            if not self.product_ids:
                 raise UserError(_("Vui lòng chọn ít nhất 1 sản phẩm để đồng bộ."))
            
            return self.product_ids.action_push_prices_to_milwaukee(api_url)
        else:
            # Sync All mapped
            mapped_products = self.env['product.template'].search([('milwaukee_id', '!=', False)])
            if not mapped_products:
                raise UserError(_("Không tìm thấy sản phẩm nào đã được map Milwaukee ID để đồng bộ."))
            return mapped_products.action_push_prices_to_milwaukee(api_url)
