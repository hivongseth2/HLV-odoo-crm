# -*- coding: utf-8 -*-
from datetime import datetime, time

import pytz

from odoo import fields, models
from odoo.exceptions import UserError


class HlvLoyaltyRecalculatePointsWizard(models.TransientModel):
    _name = 'hlv.loyalty.recalculate.points.wizard'
    _description = 'Wizard tính lại điểm Loyalty'

    account_id = fields.Many2one(
        'hlv.loyalty.portal.account',
        string='Tài khoản Portal',
        required=True,
        readonly=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Khách hàng',
        related='account_id.partner_id',
        readonly=True,
    )
    start_date = fields.Date(
        string='Tính từ ngày',
        required=True,
        default=fields.Date.context_today,
    )

    def action_recalculate(self):
        self.ensure_one()
        if not self.account_id.active:
            raise UserError('Chỉ có thể tính lại điểm cho tài khoản Portal đang hoạt động.')

        root_partner = self.account_id.partner_id._get_loyalty_root()
        partner_ids = self.env['res.partner'].sudo().with_context(active_test=False).search([
            ('id', 'child_of', root_partner.id),
        ]).ids

        user_tz = pytz.timezone(self.env.user.tz or 'UTC')
        start_date = fields.Date.to_date(self.start_date)
        start_local = user_tz.localize(datetime.combine(start_date, time.min))
        start_utc = start_local.astimezone(pytz.UTC).replace(tzinfo=None)

        pickings = self.env['stock.picking'].sudo().search([
            ('state', '=', 'done'),
            ('picking_type_code', '=', 'outgoing'),
            ('sale_id', '!=', False),
            ('sale_id.partner_id', 'in', partner_ids),
            ('date_done', '>=', start_utc),
        ], order='date_done asc, id asc')

        for picking in pickings:
            picking._loyalty_earn_points()

        return {'type': 'ir.actions.act_window_close'}
