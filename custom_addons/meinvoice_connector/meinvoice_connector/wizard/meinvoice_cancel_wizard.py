# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class MeinvoiceCancelWizard(models.TransientModel):
    _name = 'meinvoice.cancel.wizard'
    _description = 'Wizard Hủy Hóa Đơn MEinvoice'

    move_id = fields.Many2one(
        'account.move',
        string='Hóa đơn',
        required=True,
        readonly=True,
    )
    reason = fields.Text(
        string='Lý do hủy',
        required=True,
        default='Sai thông tin hóa đơn',
    )

    def action_confirm_cancel(self):
        self.ensure_one()
        move = self.move_id
        if not move.meinvoice_transaction_id:
            raise UserError(_('Hóa đơn chưa có Transaction ID MEinvoice.'))

        try:
            self.env['meinvoice.api'].api_cancel_invoice(
                [move.meinvoice_transaction_id],
                self.reason,
            )
            move.write({'meinvoice_state': 'cancelled'})
            move._meinvoice_log(
                'cancel', 'success',
                move.meinvoice_transaction_id,
                f'Đã hủy. Lý do: {self.reason}',
                {'reason': self.reason},
                {},
            )
        except Exception as e:
            move._meinvoice_log(
                'cancel', 'error',
                move.meinvoice_transaction_id,
                str(e),
                {'reason': self.reason},
                {},
            )
            raise

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title':   _('MEinvoice'),
                'message': _('Hủy hóa đơn thành công!'),
                'type':    'success',
                'sticky': False,
            },
        }
