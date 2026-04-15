# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    loyalty_total_points = fields.Integer(
        string='Tổng điểm tích lũy', compute='_compute_loyalty_total_points',
        store=True, readonly=True,
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

    @api.depends('loyalty_history_ids', 'loyalty_history_ids.point_amount')
    def _compute_loyalty_total_points(self):
        for partner in self:
            partner.loyalty_total_points = sum(
                partner.loyalty_history_ids.mapped('point_amount')
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
        """Mở wizard Đổi Voucher."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Đổi Voucher',
            'res_model': 'hlv.loyalty.redeem.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_partner_id': self.id,
            },
        }
