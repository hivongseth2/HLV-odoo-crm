# -*- coding: utf-8 -*-
import logging
from datetime import timedelta
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class HlvRedeemVoucherWizard(models.TransientModel):
    _name = 'hlv.loyalty.redeem.wizard'
    _description = 'Wizard Đổi Voucher'

    partner_id = fields.Many2one(
        'res.partner', string='Khách hàng', required=True, readonly=True,
    )
    account_id = fields.Many2one(
        'hlv.loyalty.portal.account', string='Tài khoản Loyalty', required=True,
        domain="[('partner_id', '=', partner_id), ('active', '=', True)]",
        help='Điểm bị trừ trực tiếp ở tài khoản này (mỗi công ty có thể có nhiều tài khoản).',
    )
    current_points = fields.Integer(
        string='Điểm đổi thưởng hiện tại', compute='_compute_current_points',
    )
    pending_points = fields.Integer(
        string='Điểm chờ xác nhận', compute='_compute_current_points',
    )
    reward_pending_points = fields.Integer(
        string='Điểm đang treo', compute='_compute_current_points',
    )
    available_points = fields.Integer(
        string='Điểm khả dụng', compute='_compute_current_points',
    )
    package_id = fields.Many2one(
        'hlv.loyalty.voucher.package', string='Gói Voucher',
        required=True,
        domain="[('active', '=', True)]",
    )
    points_required = fields.Integer(
        string='Điểm yêu cầu', related='package_id.points_required',
    )
    discount_info = fields.Char(
        string='Giá trị Voucher', compute='_compute_discount_info',
    )
    remaining_points = fields.Integer(
        string='Điểm còn lại sau đổi', compute='_compute_remaining_points',
    )

    @api.onchange('partner_id')
    def _onchange_partner_id_default_account(self):
        if self.partner_id:
            root = self.partner_id._get_loyalty_root()
            self.account_id = (
                root.loyalty_portal_account_ids.filtered('is_default')[:1]
                or root.loyalty_portal_account_ids[:1]
            )

    @api.depends('account_id')
    def _compute_current_points(self):
        for wiz in self:
            if not wiz.account_id:
                wiz.current_points = 0
                wiz.pending_points = 0
                wiz.reward_pending_points = 0
                wiz.available_points = 0
            else:
                account = wiz.account_id
                wiz.current_points = account.loyalty_exchange_points
                wiz.pending_points = account.loyalty_pending_points
                wiz.reward_pending_points = account.loyalty_reward_pending_points
                wiz.available_points = account.loyalty_exchange_available_points

    @api.depends('package_id')
    def _compute_discount_info(self):
        for wiz in self:
            pkg = wiz.package_id
            if not pkg:
                wiz.discount_info = ''
                continue
            if pkg.reward_type == 'free_shipping':
                wiz.discount_info = 'Miễn phí vận chuyển'
            elif pkg.reward_type == 'gift':
                if pkg.gift_product_id:
                    wiz.discount_info = f'Tặng {pkg.gift_qty:g} x {pkg.gift_product_id.display_name}'
                else:
                    wiz.discount_info = 'Quà tặng kèm'
            elif pkg.discount_type == 'fixed':
                wiz.discount_info = f'Giảm {pkg.discount_value:,.0f} VNĐ'
            else:
                info = f'Giảm {pkg.discount_value:.0f}%'
                if pkg.max_discount_amount > 0:
                    info += f' (tối đa {pkg.max_discount_amount:,.0f} VNĐ)'
                wiz.discount_info = info

    @api.depends('available_points', 'points_required')
    def _compute_remaining_points(self):
        for wiz in self:
            wiz.remaining_points = wiz.available_points - (wiz.points_required or 0)

    def action_redeem(self):
        """Thực hiện đổi điểm lấy Voucher."""
        self.ensure_one()
        partner = self.partner_id._get_loyalty_root()
        account = self.account_id
        package = self.package_id

        if not package:
            raise UserError('Vui lòng chọn Gói Voucher!')
        if not account:
            raise UserError('Vui lòng chọn Tài khoản Loyalty để trừ điểm!')

        # Validate điểm đổi thưởng
        available_points = account.loyalty_exchange_available_points
        if available_points < package.points_required:
            raise UserError(
                f'Không đủ điểm đổi thưởng! Cần {package.points_required} điểm, '
                f'hiện còn {available_points} điểm khả dụng.'
                + (f'\n({account.loyalty_reward_pending_points} điểm đang treo trong yêu cầu chờ xử lý.)' if account.loyalty_reward_pending_points > 0 else '')
            )

        # Kiểm tra quyền (chỉ Admin HQ mới được điều chỉnh)
        # Nhưng đổi voucher thì mọi nhân viên được phép

        # Tính thời hạn Voucher
        validity_days = package._get_validity_days()
        date_expiry = fields.Datetime.now() + timedelta(days=validity_days)

        # Tạo Voucher
        voucher = self.env['hlv.loyalty.voucher'].sudo().create({
            'partner_id': partner.id,
            'account_id': account.id,
            'package_id': package.id,
            'date_expiry': date_expiry,
        })

        # Trừ điểm đổi thưởng - tạo bản ghi lịch sử
        self.env['hlv.loyalty.history'].sudo().create({
            'partner_id': partner.id,
            'account_id': account.id,
            'point_amount': -package.points_required,
            'transaction_type': 'redeem',
            'point_type': 'exchange',
            'state': 'confirmed',
            'description': f'Đổi Voucher [{package.name}] - Mã: {voucher.code}',
            'voucher_id': voucher.id,
            'company_id': self.env.company.id,
        })
        account.invalidate_recordset([
            'loyalty_exchange_points',
            'loyalty_reward_pending_points',
            'loyalty_exchange_available_points',
        ])

        _logger.info(
            'Loyalty: %s (TK: %s) đổi %d điểm lấy Voucher %s (Gói: %s)',
            partner.name, account.username, package.points_required, voucher.code, package.name,
        )

        return {
            'type': 'ir.actions.act_window',
            'name': 'Voucher Loyalty',
            'res_model': 'hlv.loyalty.voucher',
            'res_id': voucher.id,
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_partner_id': partner.id,
            },
        }
