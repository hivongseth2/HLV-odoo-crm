# -*- coding: utf-8 -*-
from odoo import models, fields, api

class ZaloMiniAppBanner(models.Model):
    _name = 'zalo.miniapp.banner'
    _description = 'Zalo Mini App Banner'
    _order = 'sequence, id'

    name = fields.Char(string='Tên Banner', required=True)
    active = fields.Boolean(string='Active', default=True)
    sequence = fields.Integer(string='Thứ tự', default=10)
    image = fields.Image(string='Hình ảnh', max_width=1024, max_height=1024, required=True)
    link = fields.Char(string='Link khi click', help="Đường dẫn hoặc trang đích sẽ mở ra khi khách hàng bấm vào banner này trên ứng dụng (không bắt buộc)")
