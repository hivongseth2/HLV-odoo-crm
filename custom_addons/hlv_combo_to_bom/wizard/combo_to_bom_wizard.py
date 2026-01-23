# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ComboToBomWizard(models.TransientModel):
    _name = 'combo.to.bom.wizard'
    _description = 'Wizard chuyển Combo thành BOM'

    product_template_ids = fields.Many2many(
        'product.template',
        string='Sản phẩm Combo',
        domain=[('is_combo', '=', True)],
        required=True,
        help='Chọn các sản phẩm combo cần chuyển đổi'
    )
    
    bom_type = fields.Selection([
        ('phantom', 'Kit (Tự động giao thành phần)'),
        ('normal', 'Sản xuất'),
    ], string='Loại BOM', default='phantom', required=True,
       help='Kit: Khi bán, hệ thống tự động giao các thành phần. Sản xuất: Cần tạo lệnh sản xuất.')
    
    convert_product_type = fields.Boolean(
        string='Chuyển loại sản phẩm',
        default=True,
        help='Chuyển sản phẩm từ Dịch vụ sang Hàng hóa'
    )
    
    new_product_type = fields.Selection([
        ('storable', 'Storable (Có theo dõi tồn kho)'),
        ('goods', 'Goods (Hàng hóa - không theo dõi tồn kho)'),
    ], string='Loại sản phẩm mới', default='storable',
       help='Storable: Theo dõi tồn kho. Goods: Hàng hóa không theo dõi số lượng.')
    
    skip_existing_bom = fields.Boolean(
        string='Bỏ qua sản phẩm đã có BOM',
        default=True,
        help='Nếu sản phẩm đã có BOM, sẽ bỏ qua thay vì báo lỗi'
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        # Nếu được gọi từ action trên list view
        active_ids = self.env.context.get('active_ids', [])
        if active_ids and 'product_template_ids' in fields_list:
            # Lọc chỉ lấy các combo products
            combo_products = self.env['product.template'].browse(active_ids).filtered(
                lambda p: p.is_combo
            )
            res['product_template_ids'] = [(6, 0, combo_products.ids)]
        return res

    def action_convert(self):
        """Thực hiện chuyển đổi Combo thành BOM"""
        self.ensure_one()
        
        if not self.product_template_ids:
            raise UserError(_('Vui lòng chọn ít nhất một sản phẩm Combo.'))
        
        converted_count = 0
        skipped_count = 0
        error_messages = []
        
        for product_tmpl in self.product_template_ids:
            # Kiểm tra có phải combo không
            if not product_tmpl.is_combo:
                error_messages.append(
                    _('Sản phẩm "%s" không phải là Combo.') % product_tmpl.name
                )
                continue
            
            # Kiểm tra có combo items không
            if not product_tmpl.combo_product_id:
                error_messages.append(
                    _('Sản phẩm "%s" không có Combo Items.') % product_tmpl.name
                )
                continue
            
            # Kiểm tra đã có BOM chưa
            existing_bom = self.env['mrp.bom'].search([
                ('product_tmpl_id', '=', product_tmpl.id),
                ('active', '=', True)
            ], limit=1)
            
            if existing_bom:
                if self.skip_existing_bom:
                    skipped_count += 1
                    continue
                else:
                    raise UserError(
                        _('Sản phẩm "%s" đã có BOM. Vui lòng xóa BOM hiện tại trước khi chuyển đổi.')
                        % product_tmpl.name
                    )
            
            try:
                # Chuyển loại sản phẩm nếu được chọn (Odoo 18)
                if self.convert_product_type:
                    update_vals = {'type': 'goods'}  # Set to goods first
                    if self.new_product_type == 'storable':
                        update_vals['is_storable'] = True
                    else:
                        update_vals['is_storable'] = False
                    product_tmpl.write(update_vals)
                
                # Tạo BOM
                bom_vals = {
                    'product_tmpl_id': product_tmpl.id,
                    'type': self.bom_type,
                    'product_qty': 1.0,
                    'code': _('BOM từ Combo: %s') % product_tmpl.name,
                }
                new_bom = self.env['mrp.bom'].create(bom_vals)
                
                # Tạo BOM lines từ combo items
                for combo_item in product_tmpl.combo_product_id:
                    bom_line_vals = {
                        'bom_id': new_bom.id,
                        'product_id': combo_item.product_id.id,
                        'product_qty': combo_item.product_quantity,
                        'product_uom_id': combo_item.uom_id.id or combo_item.product_id.uom_id.id,
                    }
                    self.env['mrp.bom.line'].create(bom_line_vals)
                
                converted_count += 1
                
            except Exception as e:
                error_messages.append(
                    _('Lỗi khi chuyển đổi "%s": %s') % (product_tmpl.name, str(e))
                )
        
        # Thông báo kết quả
        message_parts = []
        if converted_count > 0:
            message_parts.append(_('Đã chuyển đổi thành công %d sản phẩm.') % converted_count)
        if skipped_count > 0:
            message_parts.append(_('Đã bỏ qua %d sản phẩm (đã có BOM).') % skipped_count)
        if error_messages:
            message_parts.append(_('Lỗi:\n') + '\n'.join(error_messages))
        
        if not message_parts:
            message_parts.append(_('Không có sản phẩm nào được chuyển đổi.'))
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Kết quả chuyển đổi'),
                'message': '\n'.join(message_parts),
                'type': 'success' if converted_count > 0 and not error_messages else 'warning',
                'sticky': True,
            }
        }

    def action_preview(self):
        """Xem trước BOM sẽ được tạo"""
        self.ensure_one()
        
        preview_lines = []
        for product_tmpl in self.product_template_ids:
            if product_tmpl.is_combo and product_tmpl.combo_product_id:
                preview_lines.append({
                    'product_name': product_tmpl.name,
                    'combo_items': [
                        {
                            'name': item.product_id.display_name,
                            'qty': item.product_quantity,
                            'uom': item.uom_id.name or item.product_id.uom_id.name,
                        }
                        for item in product_tmpl.combo_product_id
                    ]
                })
        
        # Tạo message preview
        message = _('Xem trước BOM sẽ được tạo:\n\n')
        for preview in preview_lines:
            message += f"📦 {preview['product_name']}\n"
            for item in preview['combo_items']:
                message += f"   ├─ {item['name']}: {item['qty']} {item['uom']}\n"
            message += "\n"
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Xem trước BOM'),
                'message': message,
                'type': 'info',
                'sticky': True,
            }
        }
