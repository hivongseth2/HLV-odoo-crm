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
    current_points = fields.Integer(
        string='Điểm hiện tại', compute='_compute_current_points',
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

    @api.depends('partner_id')
    def _compute_current_points(self):
        for wiz in self:
            wiz.current_points = wiz.partner_id.loyalty_total_points if wiz.partner_id else 0

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

    @api.depends('current_points', 'points_required')
    def _compute_remaining_points(self):
        for wiz in self:
            wiz.remaining_points = wiz.current_points - (wiz.points_required or 0)

    def action_redeem(self):
        """Thực hiện đổi điểm lấy Voucher."""
        self.ensure_one()
        # Luôn dùng commercial_partner_id để tích/trừ điểm
        partner = self.partner_id.commercial_partner_id or self.partner_id
        package = self.package_id

        if not package:
            raise UserError('Vui lòng chọn Gói Voucher!')

        # Validate điểm
        if partner.loyalty_total_points < package.points_required:
            raise UserError(
                f'Không đủ điểm! Cần {package.points_required} điểm, '
                f'hiện có {partner.loyalty_total_points} điểm.'
            )

        # Kiểm tra quyền (chỉ Admin HQ mới được điều chỉnh)
        # Nhưng đổi voucher thì mọi nhân viên được phép

        # Tính thời hạn Voucher
        validity_days = package._get_validity_days()
        date_expiry = fields.Datetime.now() + timedelta(days=validity_days)

        # Tạo Voucher
        voucher = self.env['hlv.loyalty.voucher'].sudo().create({
            'partner_id': partner.id,
            'package_id': package.id,
            'date_expiry': date_expiry,
        })

        # Trừ điểm - tạo bản ghi lịch sử
        self.env['hlv.loyalty.history'].sudo().create({
            'partner_id': partner.id,
            'point_amount': -package.points_required,
            'transaction_type': 'redeem',
            'description': f'Đổi Voucher [{package.name}] - Mã: {voucher.code}',
            'voucher_id': voucher.id,
            'company_id': self.env.company.id,
        })

        _logger.info(
            'Loyalty: %s đổi %d điểm lấy Voucher %s (Gói: %s)',
            partner.name, package.points_required, voucher.code, package.name,
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
