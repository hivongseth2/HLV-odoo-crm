# -*- coding: utf-8 -*-
import logging
from datetime import timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class HlvLoyaltyRewardRequest(models.Model):
    _name = 'hlv.loyalty.reward.request'
    _description = 'Yêu cầu đổi thưởng Loyalty'
    _order = 'date_request desc, id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'

    name = fields.Char(
        string='Mã yêu cầu', readonly=True, copy=False, default='New',
    )
    partner_id = fields.Many2one(
        'res.partner', string='Khách hàng', required=True,
        index=True, ondelete='restrict', tracking=True,
    )
    request_type = fields.Selection([
        ('gift', 'Đổi quà (Voucher)'),
        ('cash', 'Đổi tiền mặt'),
    ], string='Loại yêu cầu', required=True, default='gift', tracking=True)

    # ── Gift fields ────────────────────────────────────────────────────────
    package_id = fields.Many2one(
        'hlv.loyalty.voucher.package', string='Gói quà',
        domain=[('active', '=', True)],
    )

    # ── Cash fields ────────────────────────────────────────────────────────
    points_to_redeem = fields.Integer(string='Số điểm muốn đổi', default=0)
    bank_name = fields.Char(string='Ngân hàng')
    account_number = fields.Char(string='Số tài khoản')
    account_name = fields.Char(string='Chủ tài khoản')

    # ── Computed ───────────────────────────────────────────────────────────
    points_required = fields.Integer(
        string='Điểm yêu cầu', compute='_compute_points_required', store=True,
    )
    cash_value = fields.Float(
        string='Giá trị quy đổi (đ)', compute='_compute_cash_value',
        store=True, digits=(15, 0),
    )

    # ── Snapshot ───────────────────────────────────────────────────────────
    balance_at_request = fields.Integer(
        string='Số dư ĐT lúc gửi', readonly=True,
        help='Điểm đổi thưởng của khách tại thời điểm gửi yêu cầu',
    )

    # ── Notes ──────────────────────────────────────────────────────────────
    customer_note = fields.Text(string='Ghi chú của khách')
    admin_note = fields.Text(string='Ghi chú xử lý', tracking=True)

    # ── State ──────────────────────────────────────────────────────────────
    state = fields.Selection([
        ('pending', 'Chờ duyệt'),
        ('done', 'Đã xử lý'),
        ('cancelled', 'Đã hủy'),
    ], string='Trạng thái', default='pending', required=True,
        tracking=True, index=True)

    date_request = fields.Datetime(
        string='Ngày yêu cầu', default=fields.Datetime.now, readonly=True,
    )
    date_done = fields.Datetime(string='Ngày xử lý', readonly=True)
    done_by_id = fields.Many2one('res.users', string='Người xử lý', readonly=True)

    # ── Result links ───────────────────────────────────────────────────────
    history_id = fields.Many2one(
        'hlv.loyalty.history', string='Giao dịch điểm', readonly=True,
    )
    voucher_id = fields.Many2one(
        'hlv.loyalty.voucher', string='Voucher phát hành', readonly=True,
    )
    company_id = fields.Many2one(
        'res.company', string='Công ty',
        default=lambda self: self.env.company, readonly=True,
    )

    # Related point history (for admin view)
    partner_history_ids = fields.One2many(
        'hlv.loyalty.history', compute='_compute_partner_history_ids',
        string='Lịch sử điểm',
    )

    @api.depends('partner_id')
    def _compute_partner_history_ids(self):
        for rec in self:
            if rec.partner_id:
                rec.partner_history_ids = self.env['hlv.loyalty.history'].sudo().search([
                    ('partner_id', '=', rec.partner_id.id),
                ], order='date desc', limit=30)
            else:
                rec.partner_history_ids = self.env['hlv.loyalty.history']

    # ── Compute ────────────────────────────────────────────────────────────

    @api.depends('request_type', 'package_id', 'points_to_redeem')
    def _compute_points_required(self):
        for rec in self:
            if rec.request_type == 'gift' and rec.package_id:
                rec.points_required = rec.package_id.points_required
            elif rec.request_type == 'cash':
                rec.points_required = rec.points_to_redeem
            else:
                rec.points_required = 0

    @api.depends('request_type', 'points_to_redeem')
    def _compute_cash_value(self):
        program = self.env['hlv.loyalty.program'].sudo().search(
            [('active', '=', True)], limit=1
        )
        rate = program.cash_rate_per_point if program else 0.0
        for rec in self:
            if rec.request_type == 'cash' and rec.points_to_redeem > 0:
                rec.cash_value = rec.points_to_redeem * rate
            else:
                rec.cash_value = 0.0

    # ── ORM ────────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('hlv.loyalty.reward.request')
                    or 'New'
                )
        records = super().create(vals_list)
        records._send_loyalty_reward_bus_notification('request_created')
        return records

    def _get_loyalty_notification_users(self):
        self.ensure_one()
        company = self.company_id or self.env.company
        return company.sudo().loyalty_notification_user_ids.filtered(
            lambda user: user.active and user.partner_id
        )

    def _send_loyalty_reward_bus_notification(self, event):
        """Send configured in-app bus notifications for reward events."""
        bus = self.env['bus.bus'].sudo()
        for rec in self:
            users = rec._get_loyalty_notification_users()
            if not users:
                continue

            if event == 'gift_redeemed':
                title = _('Khách đã đổi quà Loyalty')
                package = rec.package_id.display_name if rec.package_id else _('Gói quà')
                voucher = rec.voucher_id.code if rec.voucher_id else ''
                message = _(
                    '%(customer)s đã đổi %(package)s (%(points)s điểm).%(voucher)s',
                    customer=rec.partner_id.display_name,
                    package=package,
                    points=f'{rec.points_required:,}',
                    voucher=f' Voucher: {voucher}' if voucher else '',
                )
            else:
                type_label = dict(rec._fields['request_type'].selection).get(rec.request_type, rec.request_type)
                title = _('Yêu cầu đổi thưởng Loyalty mới')
                message = _(
                    '%(customer)s gửi %(request_type)s %(points)s điểm. Mã: %(name)s',
                    customer=rec.partner_id.display_name,
                    request_type=type_label,
                    points=f'{rec.points_required:,}',
                    name=rec.name,
                )

            payload = {
                'title': title,
                'message': message,
                'type': 'info',
                'sticky': True,
            }
            for user in users:
                try:
                    bus._sendone(user.partner_id, 'simple_notification', payload)
                except Exception:
                    _logger.debug(
                        'Failed to send loyalty reward bus notification to user %s',
                        user.id,
                        exc_info=True,
                    )

    # ── Business logic ─────────────────────────────────────────────────────

    def _deduct_exchange_points(self, description):
        """Deduct exchange points from partner, return history record."""
        self.ensure_one()
        root = self.partner_id._get_loyalty_root()
        avail = root.loyalty_exchange_points
        if avail < self.points_required:
            raise UserError(
                f'Không đủ điểm đổi thưởng.\n'
                f'Khách hàng hiện có {avail:,} điểm, yêu cầu {self.points_required:,} điểm.'
            )
        return self.env['hlv.loyalty.history'].sudo().create({
            'partner_id': root.id,
            'point_amount': -self.points_required,
            'point_type': 'exchange',
            'transaction_type': 'redeem',
            'state': 'confirmed',
            'description': description,
            'company_id': self.company_id.id,
        })

    def _create_voucher(self):
        """Create voucher for gift request, return voucher record."""
        self.ensure_one()
        pkg = self.package_id
        program = pkg.program_id
        validity = pkg.validity_days or (program.voucher_validity_days if program else 30) or 30
        expiry = fields.Datetime.now() + timedelta(days=validity)
        root = self.partner_id._get_loyalty_root()
        return self.env['hlv.loyalty.voucher'].sudo().create({
            'partner_id': root.id,
            'package_id': pkg.id,
            'date_expiry': expiry,
        })

    def action_done(self):
        """Admin marks request as done → deduct points, create voucher if gift."""
        for rec in self:
            if rec.state != 'pending':
                raise UserError('Chỉ có thể xử lý yêu cầu đang Chờ duyệt.')
            desc = f'Đổi thưởng #{rec.name} – {rec.partner_id.name}'
            hist = rec._deduct_exchange_points(desc)
            voucher_id = False
            if rec.request_type == 'gift' and rec.package_id:
                voucher_id = rec._create_voucher().id
            rec.write({
                'state': 'done',
                'date_done': fields.Datetime.now(),
                'done_by_id': self.env.user.id,
                'history_id': hist.id,
                'voucher_id': voucher_id or False,
            })
            if rec.request_type == 'gift':
                rec._send_loyalty_reward_bus_notification('gift_redeemed')
            _logger.info(
                'Loyalty RewardRequest: %s done (%s) – %d pts deducted from %s',
                rec.name, rec.request_type, rec.points_required, rec.partner_id.name,
            )

    def action_cancel(self):
        for rec in self:
            if rec.state == 'done':
                raise UserError('Không thể hủy yêu cầu đã xử lý.')
            rec.write({'state': 'cancelled'})
