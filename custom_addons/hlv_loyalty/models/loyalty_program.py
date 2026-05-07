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

    note = fields.Html(string='Ghi chú')

    _sql_constraints = [
        ('earning_amount_positive', 'CHECK(earning_amount > 0)',
         'Số tiền quy đổi phải lớn hơn 0!'),
        ('earning_points_positive', 'CHECK(earning_points > 0)',
         'Số điểm nhận được phải lớn hơn 0!'),
    ]

    def calculate_points(self, amount):
        """Tính số điểm từ giá trị đơn hàng."""
        self.ensure_one()
        if self.earning_amount <= 0:
            return 0
        return int(amount / self.earning_amount) * self.earning_points
