# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class MilwaukeeBlogPost(models.Model):
    _name = 'milwaukee.blog.post'
    _inherit = ['milwaukee.master.mixin', 'mail.thread', 'mail.activity.mixin']
    _description = 'Milwaukee Blog Post / Article'

    name = fields.Char(string='Tiêu đề bài viết', required=True, tracking=True)
    slug = fields.Char(string='Slug bài viết', required=True, tracking=True)
    content_html = fields.Html(string='Nội dung bài viết', tracking=True)
    image_url = fields.Char(string='Ảnh đại diện (URL)', tracking=True)
    status = fields.Selection([
        ('publish', 'Đã xuất bản'),
        ('draft', 'Bản nháp')
    ], string='Trạng thái', default='draft', tracking=True)
    author_name = fields.Char(string='Tác giả', default='Admin')

    @api.model_create_multi
    def create(self, vals_list):
        records = super(MilwaukeeBlogPost, self).create(vals_list)
        for record in records:
            record._sync_to_milwaukee()
        return records

    def write(self, vals):
        res = super(MilwaukeeBlogPost, self).write(vals)
        if self.env.context.get('milwaukee_sync_done'):
            return res
        for record in self:
            record._sync_to_milwaukee()
        return res

    def _sync_to_milwaukee(self):
        self.ensure_one()
        data = {
            "title": self.name,
            "slug": self.slug,
            "content": self.content_html or "",
            "image_url": self.image_url or "",
            "status": self.status,
            "author": self.author_name
        }
        if self.milwaukee_id:
            data['id'] = self.milwaukee_id

        result = self._push_to_milwaukee('blog_posts', data)
        if result and isinstance(result, dict) and 'id' in result:
            self.with_context(milwaukee_sync_done=True).write({
                'milwaukee_id': str(result['id']),
                'last_sync_date': fields.Datetime.now()
            })
