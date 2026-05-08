# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class HlvLoyaltyProgram(models.Model):
    _name = 'hlv.loyalty.program'
    _description = 'Chương trình Khách hàng thân thiết'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'

    name = fields.Char(string='Tên chương trình', required=True, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    company_id = fields.Many2one(
        'res.company', string='Công ty sở hữu',
        required=True, default=lambda self: self.env.company,
        help='Công ty Mẹ sở hữu chương trình này',
    )
    currency_id = fields.Many2one(
        'res.currency', string='Tiền tệ',
        related='company_id.currency_id', store=True, readonly=True,
    )

    # Tỷ lệ tích điểm
    earning_amount = fields.Float(
        string='Số tiền quy đổi', required=True, default=100000,
        help='Số tiền hàng thực tế để được 1 điểm (VNĐ)',
    )
    earning_points = fields.Integer(
        string='Số điểm nhận được', required=True, default=1,
        help='Số điểm nhận được khi đạt mức tiền quy đổi',
    )
    discount_per_point = fields.Float(
        string='Mỗi X đồng chiết khấu = 1 điểm',
        required=True, default=10000,
        digits=(15, 0),
        help='Số tiền chiết khấu trên dòng hàng (VNĐ) để được 1 điểm tích lũy. VD: 10.000đ chiết khấu = 1 điểm.',
    )

    # Voucher packages
    voucher_package_ids = fields.One2many(
        'hlv.loyalty.voucher.package', 'program_id',
        string='Gói đổi Voucher',
    )

    # Cấu hình voucher mặc định
    voucher_validity_days = fields.Integer(
        string='Thời hạn Voucher (ngày)', default=30,
        help='Số ngày kể từ ngày đổi Voucher',
    )

    portal_ranking_desc = fields.Text(
        string='Mô tả Điểm Tích lũy (Portal)',
        default=(
            'Điểm tích lũy dùng để xếp hạng thành viên, không dùng để đổi thưởng. '
            'Mỗi 100.000đ mua hàng = 1 điểm.'
        ),
        help='Đoạn mô tả hiển thị cho khách hàng trên trang portal về Điểm Tích lũy.',
    )
    portal_exchange_desc = fields.Text(
        string='Mô tả Điểm Đổi thưởng (Portal)',
        default=(
            'Điểm đổi thưởng có thể dùng để đổi Voucher hoặc tiền chiết khấu. '
            'Mỗi 10.000đ chiết khấu = 1 điểm.'
        ),
        help='Đoạn mô tả hiển thị cho khách hàng trên trang portal về Điểm Đổi thưởng.',
    )

    note = fields.Html(string='Ghi chú')

    _sql_constraints = [
        ('earning_amount_positive', 'CHECK(earning_amount > 0)',
         'Số tiền quy đổi phải lớn hơn 0!'),
        ('earning_points_positive', 'CHECK(earning_points > 0)',
         'Số điểm nhận được phải lớn hơn 0!'),
    ]

    def calculate_points(self, discount_amount):
        """Tính số điểm từ tổng tiền chiết khấu trên các dòng hàng."""
        self.ensure_one()
        if self.discount_per_point <= 0:
            return 0
        return int(discount_amount / self.discount_per_point)
