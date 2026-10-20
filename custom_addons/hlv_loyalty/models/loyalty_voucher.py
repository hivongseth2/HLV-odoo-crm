# -*- coding: utf-8 -*-
import logging
import random
import string
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class HlvLoyaltyVoucher(models.Model):
    _name = 'hlv.loyalty.voucher'
    _description = 'Voucher Khách hàng thân thiết'
    _inherit = ['mail.thread']
    _rec_name = 'code'
    _order = 'create_date desc'

    code = fields.Char(
        string='Mã Voucher', required=True, copy=False,
        readonly=True, index=True,
        default=lambda self: self._generate_voucher_code(),
    )
    partner_id = fields.Many2one(
        'res.partner', string='Khách hàng', required=True,
        ondelete='restrict', index=True,
        domain="[('parent_id', '=', False)]",
    )
    account_id = fields.Many2one(
        'hlv.loyalty.portal.account', string='Tài khoản Loyalty',
        ondelete='restrict', index=True,
        help='Tài khoản Loyalty đã đổi điểm lấy voucher này.',
    )
    package_id = fields.Many2one(
        'hlv.loyalty.voucher.package', string='Gói Voucher',
        required=True, ondelete='restrict',
    )
    program_id = fields.Many2one(
        'hlv.loyalty.program', string='Chương trình',
        related='package_id.program_id', store=True, readonly=True,
    )
    company_id = fields.Many2one(
        'res.company', string='Công ty phát hành',
        related='package_id.company_id', store=True, readonly=True,
    )

    state = fields.Selection([
        ('active', 'Khả dụng'),
        ('used', 'Đã sử dụng'),
        ('expired', 'Hết hạn'),
        ('cancelled', 'Đã hủy'),
    ], string='Trạng thái', default='active', required=True, tracking=True, index=True)

    # Giá trị giảm giá
    reward_type = fields.Selection(
        related='package_id.reward_type', store=True, readonly=True,
    )
    discount_type = fields.Selection(
        related='package_id.discount_type', store=True, readonly=True,
    )
    discount_value = fields.Float(
        related='package_id.discount_value', store=True, readonly=True,
    )
    max_discount_amount = fields.Float(
        related='package_id.max_discount_amount', store=True, readonly=True,
    )
    min_order_amount = fields.Float(
        related='package_id.min_order_amount', store=True, readonly=True,
    )
    apply_on = fields.Selection(
        related='package_id.apply_on', store=True, readonly=True,
    )
    gift_product_id = fields.Many2one(
        related='package_id.gift_product_id', store=True, readonly=True,
    )
    gift_qty = fields.Float(
        related='package_id.gift_qty', store=True, readonly=True,
    )
    product_category_ids = fields.Many2many(
        related='package_id.product_category_ids', readonly=True,
    )

    # Thời hạn
    date_issued = fields.Datetime(
        string='Ngày phát hành', default=fields.Datetime.now, readonly=True,
    )
    date_expiry = fields.Datetime(string='Ngày hết hạn', readonly=True)

    # Sử dụng
    used_sale_order_id = fields.Many2one(
        'sale.order', string='Đơn hàng sử dụng', readonly=True, copy=False,
    )
    used_date = fields.Datetime(string='Ngày sử dụng', readonly=True, copy=False)
    used_company_id = fields.Many2one(
        'res.company', string='Chi nhánh sử dụng', readonly=True, copy=False,
    )

    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'Mã Voucher phải là duy nhất!'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        # Chốt ở đây vì mọi đường đổi (portal, API, Zalo, wizard nhân viên) đều tạo
        # voucher, nhưng mỗi đường tự kiểm điểm theo kiểu riêng.
        packages = self.env['hlv.loyalty.voucher.package'].sudo()
        accounts = self.env['hlv.loyalty.portal.account'].sudo()
        for vals in vals_list:
            package = packages.browse(vals.get('package_id'))
            account = accounts.browse(vals.get('account_id') or []) or None
            reason = package._get_unavailable_reason(account)
            if reason:
                raise UserError(reason)
        vouchers = super().create(vals_list)
        limited = vouchers.package_id.filtered('quota').sudo()
        if limited:
            # Kiểm lại sau khi tạo: hai lần đổi cùng lúc đều qua được bước trên.
            # Ghi redeemed_count xuống DB rồi mới đếm — xem chú thích ở field.
            limited.flush_recordset(['redeemed_count'])
            full = limited.filtered(lambda pkg: pkg.redeemed_count > pkg.quota)
            if full:
                raise UserError(f'Gói quà "{full[0].name}" đã hết suất.')
        return vouchers

    def action_cancel_voucher(self):
        """Hủy voucher chưa dùng — trả lại suất cho gói. Không tự hoàn điểm."""
        if self.filtered(lambda v: v.state != 'active'):
            raise UserError('Chỉ hủy được voucher đang Khả dụng.')
        self.write({'state': 'cancelled'})

    @api.model
    def _generate_voucher_code(self):
        """Sinh mã Voucher random unique: VHQ-XXXXXX."""
        while True:
            chars = string.ascii_uppercase + string.digits
            random_part = ''.join(random.choices(chars, k=6))
            code = f"VHQ-{random_part}"
            if not self.search_count([('code', '=', code)]):
                return code

    def compute_discount_amount(self, order_amount):
        """Tính giá trị giảm giá thực tế cho 1 đơn hàng."""
        self.ensure_one()
        if self.reward_type != 'discount':
            return 0
        if self.discount_type == 'fixed':
            return self.discount_value
        elif self.discount_type == 'percent':
            discount = order_amount * self.discount_value / 100.0
            if self.max_discount_amount > 0:
                discount = min(discount, self.max_discount_amount)
            return discount
        return 0

    @api.model
    def cron_expire_vouchers(self):
        """Cron job: Quét và đánh dấu Voucher hết hạn."""
        now = fields.Datetime.now()
        expired_vouchers = self.search([
            ('state', '=', 'active'),
            ('date_expiry', '<=', now),
            ('date_expiry', '!=', False),
        ])
        if expired_vouchers:
            expired_vouchers.write({'state': 'expired'})
            _logger.info('Đã đánh dấu %d voucher hết hạn.', len(expired_vouchers))
        return True
