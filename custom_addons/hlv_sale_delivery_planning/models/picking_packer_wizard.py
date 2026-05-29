# -*- coding: utf-8 -*-
"""Wizard: chọn người đóng gói trước khi in phiếu lấy hàng từ form view."""
from odoo import fields, models, _
from odoo.exceptions import UserError

import logging
_logger = logging.getLogger(__name__)


class StockPickingPackerPrintWizard(models.TransientModel):
    _name = 'stock.picking.packer.print.wizard'
    _description = 'Chọn người đóng gói trước khi in phiếu'

    picking_id = fields.Many2one(
        'stock.picking',
        string='Phiếu lấy hàng',
        required=True,
        ondelete='cascade',
        readonly=True,
    )
    packer_user_id = fields.Many2one(
        'res.users',
        string='Người đóng gói',
        required=True,
        domain=[('share', '=', False), ('active', '=', True)],
    )

    def action_confirm_and_print(self):
        self.ensure_one()
        picking = self.picking_id
        if not picking.exists():
            raise UserError(_('Phiếu không còn tồn tại.'))
        if not self.packer_user_id.exists():
            raise UserError(_('Người đóng gói không tồn tại.'))

        picking.action_assign_packer(self.packer_user_id.id)
        picking.mark_picking_print_started(packer_user_id=self.packer_user_id.id)
        picking.mark_picking_print_finished()

        # Try to return the picking report; fall back gracefully
        try:
            report_action = self.env.ref('stock.action_report_picking')
            return report_action.report_action(picking)
        except Exception as e:
            _logger.warning('[PackerPrintWizard] Could not get report action: %s', e)
            return {'type': 'ir.actions.act_window_close'}
