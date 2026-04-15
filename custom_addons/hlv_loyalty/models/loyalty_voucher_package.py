# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class LoyaltyVoucherPackage(models.Model):
    _name = 'loyalty.voucher.package'
    _description = 'Gói đổi Voucher'
    _rec_name = 'name'
    _order = 'points_required asc'

    name = fields.Char(string='Tên gói', required=True)
    program_id = fields.Many2one(
        'loyalty.program', string='Chương trình', required=True, ondelete='cascade',
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

    discount_type = fields.Selection([
        ('fixed', 'Giảm giá cố định (VNĐ)'),
        ('percent', 'Giảm giá phần trăm (%)'),
    ], string='Loại giảm giá', required=True, default='fixed')

    discount_value = fields.Float(
        string='Giá trị giảm', required=True,
        help='Giá trị giảm giá: số tiền (VNĐ) hoặc phần trăm (%)',
    )
    max_discount_amount = fields.Float(
        string='Giảm tối đa (VNĐ)', default=0,
        help='Áp dụng cho loại phần trăm. 0 = không giới hạn',
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
        ('discount_value_positive', 'CHECK(discount_value > 0)',
         'Giá trị giảm giá phải lớn hơn 0!'),
    ]

    def _get_validity_days(self):
        """Lấy thời hạn Voucher: ưu tiên gói > chương trình."""
        self.ensure_one()
        return self.validity_days or self.program_id.voucher_validity_days or 30
