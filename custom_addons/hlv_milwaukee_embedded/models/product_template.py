# -*- coding: utf-8 -*-
import json
from odoo import models, fields, api, _

class ProductTemplate(models.Model):
    _name = 'product.template'
    _inherit = ['product.template', 'milwaukee.master.mixin']

    milwaukee_slug = fields.Char(string='Milwaukee Slug', help="Đường dẫn thân thiện (Product Path)")
    milwaukee_specs = fields.Text(string='Sản phẩm Specs (JSON)', help="Các thuộc tính kỹ thuật (JSON format)")
    milwaukee_gallery_urls = fields.Text(string='Gallery URLs (JSON)', help="Mảng các URL ảnh (JSON format)")
    milwaukee_status = fields.Selection([
        ('publish', 'Đã xuất bản'),
        ('draft', 'Bản nháp'),
        ('archived', 'Lưu trữ')
    ], string='Trạng thái Website', default='draft')

    # Tắt tự động sync để tránh ảnh hưởng đến các module khác (như MISA sync)
    # Người dùng sẽ bấm nút "Push to Milwaukee" thủ công khi cần.

    def _sync_to_milwaukee(self):
        """Prepare data and push to master API"""
        self.ensure_one()
        
        # Parse JSON fields safely
        try:
            specs = json.loads(self.milwaukee_specs or '{}')
        except:
            specs = {}
            
        try:
            gallery = json.loads(self.milwaukee_gallery_urls or '[]')
        except:
            gallery = []

        data = {
            "title": self.name,
            "sku": self.default_code or "",
            "slug": self.milwaukee_slug or self.default_code or "",
            "price": float(self.list_price),
            "status": self.milwaukee_status,
            "specs": specs,
            "gallery_urls": gallery
        }
        
        # Nếu đã có ID thì gửi kèm để Update
        if self.milwaukee_id:
            data['id'] = self.milwaukee_id

        result = self._push_to_milwaukee('products', data)
        if result and isinstance(result, dict) and 'id' in result:
            # Lưu lại ID trả về từ Master (trong trường hợp tạo mới)
            self.with_context(milwaukee_sync_done=True).write({
                'milwaukee_id': str(result['id']),
                'last_sync_date': fields.Datetime.now()
            })
