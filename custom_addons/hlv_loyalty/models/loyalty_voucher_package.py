# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class HlvLoyaltyVoucherPackage(models.Model):
    _name = 'hlv.loyalty.voucher.package'
    _description = 'Gói đổi Voucher'
    _rec_name = 'name'
    _order = 'points_required asc'

    name = fields.Char(string='Tên gói', required=True)
    program_id = fields.Many2one(
        'hlv.loyalty.program', string='Chương trình', required=True, ondelete='cascade',
    )
    company_id = fields.Many2one(
        'res.company', string='Công ty',
        related='program_id.company_id', store=True, readonly=True,
    )
    active = fields.Boolean(default=True)

    points_required = fields.Integer(
        string='Điểm yêu cầu', required=True,
        help='Số điểm cần thiết để đổi gói Voucher này',
    )

    reward_type = fields.Selection([
        ('discount', 'Đổi giảm giá'),
        ('free_shipping', 'Đổi miễn phí vận chuyển'),
        ('gift', 'Đổi quà tặng kèm'),
    ], string='Chương trình đổi thưởng', required=True, default='discount')

    discount_type = fields.Selection([
        ('fixed', 'Giảm giá cố định (VNĐ)'),
        ('percent', 'Giảm giá phần trăm (%)'),
    ], string='Loại giảm giá', default='fixed')

    discount_value = fields.Float(
        string='Giá trị giảm', default=0,
        help='Giá trị giảm giá: số tiền (VNĐ) hoặc phần trăm (%)',
    )
    max_discount_amount = fields.Float(
        string='Giảm tối đa (VNĐ)', default=0,
        help='Áp dụng cho loại phần trăm. 0 = không giới hạn',
    )
    gift_product_id = fields.Many2one(
        'product.product', string='Sản phẩm quà tặng',
        help='Sản phẩm được tặng khi đổi theo chương trình quà tặng kèm',
    )
    gift_qty = fields.Float(
        string='Số lượng quà tặng', default=1,
    )

    validity_days = fields.Integer(
        string='Thời hạn (ngày)', default=0,
        help='Thời hạn Voucher. 0 = dùng thời hạn từ chương trình',
    )

    # Phạm vi áp dụng
    apply_on = fields.Selection([
        ('all', 'Tất cả sản phẩm'),
        ('category', 'Theo danh mục sản phẩm'),
    ], string='Áp dụng cho', default='all')

    product_category_ids = fields.Many2many(
        'product.category', string='Danh mục sản phẩm',
        help='Chỉ áp dụng cho sản phẩm thuộc các danh mục này',
    )
    min_order_amount = fields.Float(
        string='Giá trị đơn hàng tối thiểu', default=0,
        help='Đơn hàng phải đạt giá trị tối thiểu này mới áp dụng Voucher. 0 = không yêu cầu',
    )

    _sql_constraints = [
        ('points_required_positive', 'CHECK(points_required > 0)',
         'Số điểm yêu cầu phải lớn hơn 0!'),
        ('discount_value_non_negative', 'CHECK(discount_value >= 0)',
         'Giá trị giảm giá không được nhỏ hơn 0!'),
    ]

    @api.constrains('reward_type', 'discount_type', 'discount_value', 'max_discount_amount', 'gift_product_id', 'gift_qty')
    def _check_reward_configuration(self):
        for rec in self:
            if rec.reward_type == 'discount':
                if not rec.discount_type:
                    raise ValidationError('Vui lòng chọn loại giảm giá cho chương trình đổi giảm giá!')
                if rec.discount_value <= 0:
                    raise ValidationError('Giá trị giảm giá phải lớn hơn 0!')
                if rec.discount_type == 'percent' and rec.discount_value > 100:
                    raise ValidationError('Giảm giá phần trăm không được vượt quá 100%!')
                if rec.max_discount_amount < 0:
                    raise ValidationError('Giảm tối đa không được nhỏ hơn 0!')

            if rec.reward_type == 'gift':
                if not rec.gift_product_id:
                    raise ValidationError('Vui lòng chọn sản phẩm quà tặng!')
                if rec.gift_qty <= 0:
                    raise ValidationError('Số lượng quà tặng phải lớn hơn 0!')

    def _get_validity_days(self):
        """Lấy thời hạn Voucher: ưu tiên gói > chương trình."""
        self.ensure_one()
        return self.validity_days or self.program_id.voucher_validity_days or 30
