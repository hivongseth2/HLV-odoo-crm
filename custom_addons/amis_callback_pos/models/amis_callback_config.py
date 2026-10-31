# -*- coding: utf-8 -*-
from odoo import fields, models


class AmisCallbackConfigPos(models.Model):
    _inherit = 'amis.callback.config'

    meinvoice_pos_enabled = fields.Boolean(
        string='Tạo HĐĐT nháp cho đơn POS',
        default=False,
        help='Bật: mỗi đơn POS thanh toán xong được tạo một hóa đơn điện tử nháp. '
             'Không tự gửi CQT — kế toán duyệt rồi bấm "Gửi lên Cơ quan Thuế".',
    )
    meinvoice_pos_inv_series = fields.Char(
        string='Ký hiệu HĐ cho đơn POS',
        default='1C26MLV',
        help='Ký hiệu hóa đơn dùng cho đơn POS, tách khỏi ký hiệu của đơn Shopee. '
             'Để trống thì dùng ký hiệu chung của cấu hình meInvoice.',
    )
    meinvoice_pos_consumer_name = fields.Char(
        string='Tên người mua khi bán cho người tiêu dùng',
        default='Bán cho người tiêu dùng',
        help='Ghi khi khách của đơn POS không có MST.',
    )
    meinvoice_pos_consumer_partner_ids = fields.Many2many(
        'res.partner',
        'amis_config_pos_consumer_partner_rel',
        'config_id',
        'partner_id',
        string='Khách luôn xuất cho người tiêu dùng',
        help='Khách lẻ chung của quầy (vd. "Khách lẻ") — dù có MST cũng xuất '
             'hóa đơn bán cho người tiêu dùng.',
    )
