# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    loyalty_total_points = fields.Integer(
        string='Điểm xếp hạng', compute='_compute_loyalty_total_points',
        store=True, readonly=True,
        help='Điểm tự động xác nhận, dùng để tính hạng thành viên.',
    )
    loyalty_exchange_points = fields.Integer(
        string='Điểm đổi thưởng', compute='_compute_loyalty_exchange_points',
        store=True, readonly=True,
        help='Điểm đã được nhân viên xác nhận, dùng để đổi Voucher.',
    )
    loyalty_pending_points = fields.Integer(
        string='Điểm chờ xác nhận', compute='_compute_loyalty_pending_points',
        store=False, readonly=True,
    )
    loyalty_reward_pending_points = fields.Integer(
        string='Điểm đổi thưởng đang treo',
        compute='_compute_loyalty_reward_request_points',
        store=False, readonly=True,
        help='Tổng điểm của các yêu cầu đổi thưởng đang chờ xử lý. Điểm này chưa bị trừ khỏi số dư thật nhưng không còn khả dụng để tạo yêu cầu mới.',
    )
    loyalty_exchange_available_points = fields.Integer(
        string='Điểm đổi thưởng khả dụng',
        compute='_compute_loyalty_reward_request_points',
        store=False, readonly=True,
        help='Điểm đổi thưởng còn có thể dùng sau khi trừ điểm đang treo ở các yêu cầu chờ xử lý.',
    )
    loyalty_history_ids = fields.One2many(
        'hlv.loyalty.history', 'partner_id', string='Lịch sử điểm',
    )
    loyalty_history_count = fields.Integer(
        string='Số giao dịch', compute='_compute_loyalty_counts',
    )
    loyalty_voucher_ids = fields.One2many(
        'hlv.loyalty.voucher', 'partner_id', string='Voucher',
    )
    loyalty_voucher_count = fields.Integer(
        string='Số Voucher', compute='_compute_loyalty_counts',
    )
    loyalty_tier_id = fields.Many2one(
        'hlv.loyalty.tier', string='Hạng thành viên',
        compute='_compute_loyalty_tier', store=False, readonly=True,
    )
    loyalty_default_discount = fields.Float(
        string='% Chiết khấu mặc định (Loyalty)',
        default=0.05,
        digits=(5, 4),
        help='Tỉ lệ chiết khấu mặc định để tính điểm Loyalty khi dòng hàng không có loyalty_discount_pct. '
             'Nhập theo dạng thập phân: 0.05 = 5%, 0.1 = 10%. Admin có thể sửa trên từng khách hàng.',
    )
    loyalty_portal_account_ids = fields.One2many(
        'hlv.loyalty.portal.account', 'partner_id', string='Tài khoản Portal',
    )

    @api.depends(
        'loyalty_portal_account_ids.loyalty_total_points',
        'loyalty_history_ids', 'loyalty_history_ids.point_amount',
        'loyalty_history_ids.point_type', 'loyalty_history_ids.state',
    )
    def _compute_loyalty_total_points(self):
        """Điểm xếp hạng: tổng hợp (rollup) từ các tài khoản Loyalty của công ty.

        Đây là số CHỈ ĐỂ XEM — nguồn sự thật thật sự nằm ở
        `hlv.loyalty.portal.account.loyalty_total_points` (mỗi tài khoản có
        pool điểm xếp hạng riêng). Với partner không phải root (hiếm, dữ
        liệu legacy), giữ hành vi cũ: chỉ tính lịch sử gắn trực tiếp vào
        chính partner đó (partner không có tài khoản Loyalty riêng).
        """
        History = self.env['hlv.loyalty.history']
        for partner in self:
            if not partner.parent_id and partner.loyalty_portal_account_ids:
                partner.loyalty_total_points = sum(
                    partner.loyalty_portal_account_ids.mapped('loyalty_total_points')
                )
                continue
            records = History.search([
                ('partner_id', '=', partner.id),
                ('point_type', 'in', ['ranking', False]),
                ('state', 'in', ['confirmed', False]),
            ])
            partner.loyalty_total_points = sum(records.mapped('point_amount'))

    @api.depends('loyalty_portal_account_ids.loyalty_exchange_points')
    def _compute_loyalty_exchange_points(self):
        """Điểm đổi thưởng: tổng hợp (rollup) CHỈ ĐỂ XEM từ các tài khoản của
        công ty — công ty không còn giữ pool điểm đổi thưởng riêng, mọi
        việc đổi/trừ điểm thật sự xảy ra ở từng `hlv.loyalty.portal.account`.
        """
        for partner in self:
            partner.loyalty_exchange_points = sum(
                partner.loyalty_portal_account_ids.mapped('loyalty_exchange_points')
            )

    @api.depends('loyalty_portal_account_ids.loyalty_pending_points')
    def _compute_loyalty_pending_points(self):
        """Điểm exchange đang chờ xác nhận — tổng hợp từ các tài khoản."""
        for partner in self:
            partner.loyalty_pending_points = sum(
                partner.loyalty_portal_account_ids.mapped('loyalty_pending_points')
            )

    def _get_loyalty_family_partner_ids(self):
        self.ensure_one()
        root = self._get_loyalty_root()
        return [root.id] + root.child_ids.ids

    def _get_loyalty_pending_reward_requests(self, exclude_request=None):
        self.ensure_one()
        domain = [
            ('partner_id', 'in', self._get_loyalty_family_partner_ids()),
            ('state', '=', 'pending'),
        ]
        exclude_ids = []
        if exclude_request:
            exclude_ids = exclude_request.ids if hasattr(exclude_request, 'ids') else [int(exclude_request)]
        if exclude_ids:
            domain.append(('id', 'not in', exclude_ids))
        return self.env['hlv.loyalty.reward.request'].sudo().search(domain)

    def _get_loyalty_pending_reward_points(self, exclude_request=None):
        self.ensure_one()
        requests = self._get_loyalty_pending_reward_requests(exclude_request=exclude_request)
        return sum(requests.mapped('points_required'))

    @api.depends('loyalty_exchange_points')
    def _compute_loyalty_reward_request_points(self):
        for partner in self:
            pending_points = partner._get_loyalty_pending_reward_points()
            partner.loyalty_reward_pending_points = pending_points
            partner.loyalty_exchange_available_points = max((partner.loyalty_exchange_points or 0) - pending_points, 0)

    @api.depends('loyalty_total_points')
    def _compute_loyalty_tier(self):
        tiers = self.env['hlv.loyalty.tier'].sudo().search(
            [('active', '=', True)], order='min_points desc'
        )
        for partner in self:
            pts = partner.loyalty_total_points
            partner.loyalty_tier_id = next(
                (t for t in tiers if pts >= t.min_points), False
            )

    def _compute_loyalty_counts(self):
        history_data = self.env['hlv.loyalty.history'].sudo()._read_group(
            [('partner_id', 'in', self.ids)],
            ['partner_id'],
            ['__count'],
        )
        history_map = {partner.id: count for partner, count in history_data}

        voucher_data = self.env['hlv.loyalty.voucher'].sudo()._read_group(
            [('partner_id', 'in', self.ids)],
            ['partner_id'],
            ['__count'],
        )
        voucher_map = {partner.id: count for partner, count in voucher_data}

        for partner in self:
            partner.loyalty_history_count = history_map.get(partner.id, 0)
            partner.loyalty_voucher_count = voucher_map.get(partner.id, 0)

    def _get_loyalty_root(self):
        """Return the topmost partner in the parent chain for loyalty operations.

        Unlike commercial_partner_id (which stops at the first is_company=True),
        this walks all the way up so company-type branches (is_company=True with
        parent_id) share the same loyalty balance as their parent company.
        """
        self.ensure_one()
        partner = self
        while partner.parent_id:
            partner = partner.parent_id
        return partner

    def action_view_loyalty_history(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Lịch sử điểm',
            'res_model': 'hlv.loyalty.history',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }

    def action_view_loyalty_vouchers(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Voucher của tôi',
            'res_model': 'hlv.loyalty.voucher',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }

    def action_open_redeem_wizard(self):
        """Mở wizard Đổi Voucher - luôn dùng công ty gốc."""
        self.ensure_one()
        root_partner = self.commercial_partner_id or self
        return {
            'type': 'ir.actions.act_window',
            'name': 'Đổi Voucher',
            'res_model': 'hlv.loyalty.redeem.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_partner_id': root_partner.id,
            },
        }

    def action_open_point_adjustment_wizard(self):
        """Mở wizard Điều chỉnh điểm thủ công."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Điều chỉnh điểm',
            'res_model': 'hlv.loyalty.point.adjustment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_partner_id': self.id,
            },
        }
