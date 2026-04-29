# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class MilwaukeeBanner(models.Model):
    _name = 'milwaukee.banner'
    _inherit = ['milwaukee.master.mixin']
    _description = 'Milwaukee Website Banner'
    _order = 'sequence, id'

    name = fields.Char(string='Tiêu đề Banner', required=True, tracking=True)
    image_url = fields.Char(string='URL Ảnh (CDN)', required=True, tracking=True)
    link_url = fields.Char(string='Link khi nhấn', tracking=True)
    status = fields.Selection([
        ('publish', 'Đã xuất bản'),
        ('draft', 'Bản nháp')
    ], string='Trạng thái', default='draft', tracking=True)
    sequence = fields.Integer(string='Thứ tự hiển thị', default=10)
    description = fields.Text(string='Mô tả ngắn')

    # Tắt tự động sync. Người dùng sẽ bấm nút "Push to Milwaukee" thủ công.

    def _sync_to_milwaukee(self):
        self.ensure_one()
        data = {
            "title": self.name,
            "image_url": self.image_url,
            "link_url": self.link_url or "",
            "status": self.status,
            "sequence": self.sequence,
            "description": self.description or ""
        }
        if self.milwaukee_id:
            data['id'] = self.milwaukee_id

        result = self._push_to_milwaukee('banners', data)
        if result and isinstance(result, dict) and 'id' in result:
            self.with_context(milwaukee_sync_done=True).write({
                'milwaukee_id': str(result['id']),
                'last_sync_date': fields.Datetime.now()
            })
