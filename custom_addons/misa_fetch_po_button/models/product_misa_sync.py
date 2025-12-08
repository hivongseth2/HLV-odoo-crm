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