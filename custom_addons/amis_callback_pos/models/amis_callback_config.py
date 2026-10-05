# -*- coding: utf-8 -*-
from odoo import fields, models


class AmisCallbackConfigPos(models.Model):
    _inherit = 'amis.callback.config'

    meinvoice_pos_enabled = fields.Boolean(
        string='Tạo HĐĐT cho đơn POS',
        default=False,
        help='Bật: mỗi đơn POS thanh toán xong được tạo một hóa đơn điện tử nháp. '
             'Dùng chung ký hiệu hóa đơn (máy tính tiền) của cấu hình meInvoice.',
    )
    meinvoice_pos_auto_publish = fields.Boolean(
        string='Phát hành ngay lên CQT (POS)',
        default=True,
        help='Bật: hóa đơn nháp của đơn POS được gửi CQT ngay sau khi lưu đơn '
             '(qua cron, không bắt thu ngân chờ). Tắt: chỉ tạo nháp để kế toán '
             'xem trước rồi tự gửi — nên tắt trong những ngày chạy thử đầu.',
    )
    meinvoice_pos_buyer_mode = fields.Selection(
        [
            ('consumer', 'Luôn bán cho người tiêu dùng'),
            ('partner_vat', 'Lấy thông tin khách nếu khách có MST'),
        ],
        string='Người mua trên HĐĐT POS',
        default='consumer',
        required=True,
    )
    meinvoice_pos_consumer_name = fields.Char(
        string='Tên người mua khi bán cho người tiêu dùng',
        default='Bán cho người tiêu dùng',
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
