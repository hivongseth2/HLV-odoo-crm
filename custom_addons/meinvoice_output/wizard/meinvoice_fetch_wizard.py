# -*- coding: utf-8 -*-
from datetime import date, timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class MeinvoiceFetchWizard(models.TransientModel):
    _name = 'meinvoice.fetch.wizard'
    _description = 'Lấy hóa đơn từ meInvoice'

    from_date = fields.Date(
        'Từ ngày', required=True,
        default=lambda self: date.today().replace(day=1),
    )
    to_date = fields.Date(
        'Đến ngày', required=True,
        default=lambda self: date.today(),
    )
    accounting_status = fields.Selection([
        ('all', 'Tất cả'),
        ('0',   'Chưa hạch toán'),
        ('1',   'Đã hạch toán'),
    ], string='Trạng thái hạch toán', default='all')
    organization_id = fields.Char(
        'Organization ID',
        help='Để trống = lấy tất cả organizations. '
             'Điền ID cụ thể nếu có nhiều chi nhánh.',
    )

    @api.constrains('from_date', 'to_date')
    def _check_dates(self):
        for rec in self:
            if rec.from_date > rec.to_date:
                raise UserError(_('Từ ngày phải nhỏ hơn hoặc bằng Đến ngày.'))
            if (rec.to_date - rec.from_date).days > 30:
                raise UserError(_('Khoảng thời gian không được quá 30 ngày (giới hạn API meInvoice).'))

    def action_fetch(self):
        self.ensure_one()
        acc_status = None if self.accounting_status == 'all' else int(self.accounting_status)

        created, updated, skipped = self.env['meinvoice.output.invoice'].sync_from_meinvoice(
            from_date=str(self.from_date),
            to_date=str(self.to_date),
            organization_id=self.organization_id or '',
            accounting_status=acc_status,
        )

        msg = _(
            'Đồng bộ hoàn tất!\n'
            '• Mới tạo: %d\n'
            '• Cập nhật: %d\n'
            '• Bỏ qua (đã có): %d'
        ) % (created, updated, skipped)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title':   _('meInvoice – Đồng bộ hóa đơn đầu ra'),
                'message': msg,
                'type':    'success',
                'sticky': True,
            },
        }
