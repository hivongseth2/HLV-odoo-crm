# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class MeinvoiceAdjustWizard(models.TransientModel):
    _name = 'meinvoice.adjust.wizard'
    _description = 'Wizard Điều Chỉnh Hóa Đơn MEinvoice'

    move_id = fields.Many2one(
        'account.move',
        string='Hóa đơn gốc',
        required=True,
        readonly=True,
    )
    adjust_type = fields.Selection([
        ('1', 'Điều chỉnh tăng'),
        ('2', 'Điều chỉnh giảm'),
        ('3', 'Thay thế hóa đơn'),
    ], string='Loại điều chỉnh', required=True, default='1')
    reason = fields.Text(
        string='Lý do điều chỉnh',
        required=True,
    )
    new_move_id = fields.Many2one(
        'account.move',
        string='Hóa đơn điều chỉnh (Odoo)',
        domain=[('move_type', 'in', ['out_invoice', 'out_refund']),
                ('state', '=', 'posted')],
        help='Chọn hóa đơn Odoo chứa dữ liệu điều chỉnh mới. '
             'Nếu không chọn, sẽ dùng lại dữ liệu hóa đơn gốc.',
    )

    def action_confirm_adjust(self):
        self.ensure_one()
        orig = self.move_id
        if not orig.meinvoice_transaction_id:
            raise UserError(_('Hóa đơn gốc chưa có Transaction ID MEinvoice.'))

        source_move = self.new_move_id or orig
        invoice_data = source_move._meinvoice_build_invoice_data()

        try:
            result = self.env['meinvoice.api'].api_adjust_invoice(
                org_transaction_id=orig.meinvoice_transaction_id,
                adjust_type=int(self.adjust_type),
                invoice_data=invoice_data,
                reason=self.reason,
            )
            new_txn = (
                result if isinstance(result, str)
                else (result or {}).get('TransactionID', '')
            )
            orig.write({'meinvoice_state': 'adjusted'})
            orig._meinvoice_log(
                'adjust', 'success',
                new_txn,
                f'Điều chỉnh loại {self.adjust_type}. Lý do: {self.reason}. '
                f'Transaction mới: {new_txn}',
                {'adjust_type': self.adjust_type, 'reason': self.reason},
                result,
            )
        except Exception as e:
            orig._meinvoice_log(
                'adjust', 'error',
                orig.meinvoice_transaction_id,
                str(e),
                {'adjust_type': self.adjust_type, 'reason': self.reason},
                {},
            )
            raise

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title':   _('MEinvoice'),
                'message': _('Điều chỉnh hóa đơn thành công!'),
                'type':    'success',
                'sticky': False,
            },
        }
