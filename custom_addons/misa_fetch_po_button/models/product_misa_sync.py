# models/product_misa_sync.py

from odoo import models, fields, api, _
from odoo.exceptions import UserError

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # Trường lưu ID MISA để biết đã đồng bộ chưa
    misa_product_id = fields.Char(string="MISA Product ID", copy=False, readonly=True)
    misa_synced_date = fields.Datetime(string="Ngày đồng bộ MISA", readonly=True)

    def action_sync_to_misa(self):
        """Action được gọi từ nút bấm trên View"""
        self.ensure_one()
        
        # 1. Validate dữ liệu Odoo
        if not self.default_code:
            raise UserError(_("Vui lòng nhập 'Mã nội bộ' (Internal Reference) trước khi đồng bộ."))
        
        misa_utils = self.env['misa.api.utils']
        
        try:
            # 2. Gọi hàm utils vừa viết
            misa_id = misa_utils.create_product_in_misa(self)
            
            # 3. Cập nhật lại vào Odoo nếu thành công
            if misa_id:
                self.write({
                    'misa_product_id': str(misa_id),
                    'misa_synced_date': fields.Datetime.now()
                })
                
                # Hiển thị thông báo thành công
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _("Thành công"),
                        'message': _(f"Đã tạo sản phẩm {self.default_code} trên MISA CRM."),
                        'type': 'success',
                        'sticky': False,
                    }
                }
                
        except Exception as e:
            # Hiển thị lỗi ra màn hình cho user
            raise UserError(_("Đồng bộ thất bại:\n%s") % str(e))