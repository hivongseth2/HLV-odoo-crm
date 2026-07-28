# -*- coding: utf-8 -*-
from odoo import models, fields


class PosCategory(models.Model):
    _inherit = 'pos.category'

    x_is_featured_zalo = fields.Boolean(
        string='Nổi bật Zalo Mini App',
        default=False,
        help='Tích chọn danh mục nổi bật. 7 danh mục có thứ tự ưu tiên (sequence) cao nhất sẽ xuất hiện ngoài Trang chủ Zalo Mini App, tất cả danh mục nổi bật sẽ nằm trong trang Xem thêm.',
    )
