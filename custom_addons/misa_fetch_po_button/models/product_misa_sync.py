from odoo import models, fields, api, _
from odoo.exceptions import UserError

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    misa_product_id = fields.Char(string="MISA ID", copy=False, readonly=True)
    misa_synced_date = fields.Datetime(string="Ngày đồng bộ", readonly=True)

    def action_sync_to_misa(self):
        self.ensure_one()
        
        # Gọi hàm mới trong Utils
        try:
            # Truyền self.id vào hàm mới
            misa_id = self.env['misa.api.utils'].create_product_misa(self.id)
            
            if misa_id:
                self.write({
                    'misa_product_id': str(misa_id),
                    'misa_synced_date': fields.Datetime.now()
                })
                
                # Hiển thị thông báo Toast thành công
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _("Thành công"),
                        'message': _("Đã tạo sản phẩm trên MISA"),
                        'type': 'success',
                        'sticky': False,
                    }
                }
        except Exception as e:
            # Hiện popup lỗi nếu có sự cố
            raise UserError(_("Lỗi đồng bộ MISA:\n%s") % str(e))

    def write(self, vals):
        # Lưu các giá trị cũ của trường chuẩn bị thay đổi trước khi ghi
        old_misa_values = {}
        if 'name' in vals or 'default_code' in vals:
            for rec in self:
                old_misa_values[rec.id] = {
                    'name': rec.name or '',
                    'default_code': rec.default_code or '',
                }

        res = super(ProductTemplate, self).write(vals)

        # Cập nhật thay đổi sang MISA
        if old_misa_values:
            misa_utils = self.env['misa.api.utils']
            for rec in self:
                old_vals = old_misa_values.get(rec.id)
                if not old_vals:
                    continue
                
                old_code = old_vals['default_code']
                if not old_code:
                    continue
                
                try:
                    # Dùng mã tham chiếu cũ (default_code) search trên MISA để lấy ID sản phẩm
                    search_res = misa_utils.search_product_by_name(code=old_code)
                    misa_id = None
                    if search_res:
                        for p in search_res:
                            # So sánh chính xác ProductCode trên MISA với old_code
                            if p.get('code') == old_code:
                                misa_id = str(p.get('misa_id'))
                                break
                    
                    if misa_id:
                        if 'name' in vals:
                            new_name = rec.name or ''
                            if new_name != old_vals['name']:
                                misa_utils.update_product_field_misa(misa_id, 'name', new_name, old_vals['name'])
                        
                        if 'default_code' in vals:
                            new_code = rec.default_code or ''
                            if new_code != old_code:
                                misa_utils.update_product_field_misa(misa_id, 'code', new_code, old_code)
                except Exception as e:
                    # Log lỗi nhưng không chặn luồng update trong Odoo
                    # _logger.error("Lỗi đồng bộ cập nhật sản phẩm MISA: %s", str(e))
                    pass
                        
        return res