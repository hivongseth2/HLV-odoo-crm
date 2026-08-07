# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class HlvLoyaltyPointTransferWizard(models.TransientModel):
    _name = 'hlv.loyalty.point.transfer.wizard'
    _description = 'Wizard Chuyển điểm đổi thưởng giữa các tài khoản Loyalty'

    source_account_id = fields.Many2one(
        'hlv.loyalty.portal.account', string='Từ tài khoản', required=True,
    )
    destination_account_id = fields.Many2one(
        'hlv.loyalty.portal.account', string='Sang tài khoản', required=True,
        domain="[('partner_id', '=', source_partner_id), ('id', '!=', source_account_id)]",
    )
    source_partner_id = fields.Many2one(
        'res.partner', string='Công ty', related='source_account_id.partner_id', readonly=True,
    )
    source_available_points = fields.Integer(
        string='Điểm khả dụng (nguồn)', related='source_account_id.loyalty_exchange_available_points',
        readonly=True,
    )
    points = fields.Integer(string='Số điểm chuyển', required=True)
    note = fields.Char(string='Ghi chú')

    @api.constrains('source_account_id', 'destination_account_id')
    def _check_same_company(self):
        for wiz in self:
            if not wiz.source_account_id or not wiz.destination_account_id:
                continue
            if wiz.source_account_id.id == wiz.destination_account_id.id:
                raise ValidationError('Tài khoản nguồn và tài khoản đích phải khác nhau.')
            if wiz.source_account_id.partner_id.id != wiz.destination_account_id.partner_id.id:
                raise ValidationError(
                    'Chỉ có thể chuyển điểm giữa các tài khoản Loyalty trong cùng 1 công ty.'
                )

    @api.constrains('points')
    def _check_points(self):
        for wiz in self:
            if wiz.points <= 0:
                raise UserError('Số điểm chuyển phải lớn hơn 0.')

    def action_transfer(self):
        self.ensure_one()
        source = self.source_account_id
        destination = self.destination_account_id
        points = self.points

        available = source.loyalty_exchange_available_points
        if points > available:
            raise UserError(
                f'Không đủ điểm để chuyển.\n'
                f'Tài khoản "{source.display_name}" hiện có {available:,} điểm khả dụng, '
                f'yêu cầu chuyển {points:,} điểm.'
            )

        note_suffix = f' - {self.note}' if self.note else ''
        History = self.env['hlv.loyalty.history'].sudo()
        History.create({
            'partner_id': source.partner_id.id,
            'account_id': source.id,
            'point_amount': -points,
            'point_type': 'exchange',
            'transaction_type': 'transfer',
            'state': 'confirmed',
            'description': f'Chuyển điểm sang tài khoản "{destination.display_name}"{note_suffix}',
            'company_id': self.env.company.id,
        })
        History.create({
            'partner_id': destination.partner_id.id,
            'account_id': destination.id,
            'point_amount': points,
            'point_type': 'exchange',
            'transaction_type': 'transfer',
            'state': 'confirmed',
            'description': f'Nhận điểm chuyển từ tài khoản "{source.display_name}"{note_suffix}',
            'company_id': self.env.company.id,
        })
        (source | destination).invalidate_recordset([
            'loyalty_exchange_points',
            'loyalty_reward_pending_points',
            'loyalty_exchange_available_points',
        ])

        _logger.info(
            'Loyalty: Chuyển %d điểm từ TK %s sang TK %s (công ty %s)',
            points, source.username, destination.username, source.partner_id.name,
        )
        return {'type': 'ir.actions.act_window_close'}
