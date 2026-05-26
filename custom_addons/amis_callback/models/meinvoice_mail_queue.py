# -*- coding: utf-8 -*-
from odoo import fields, models
from odoo.exceptions import UserError


class MeinvoiceMailQueue(models.Model):
    _name = 'meinvoice.mail.queue'
    _description = 'Queue gửi email HĐĐT'
    _order = 'create_date desc'
    _rec_name = 'invoice_id'

    invoice_id = fields.Many2one(
        'meinvoice.invoice', string='Hóa đơn', required=True,
        ondelete='cascade', index=True,
    )
    mode = fields.Selection(
        [('draft', 'Bản nháp'), ('published', 'Bản chính thức')],
        string='Loại email', required=True,
    )
    email_to = fields.Char(string='Email gửi đến')
    status = fields.Selection(
        [
            ('pending',  'Chờ xử lý'),
            ('sent',     'Đã gửi'),
            ('failed',   'Thất bại'),
            ('skipped',  'Bỏ qua'),
        ],
        string='Trạng thái', default='pending', required=True, index=True,
    )
    reason = fields.Char(string='Lý do / Ghi chú')
    sent_at = fields.Datetime(string='Thời gian gửi', readonly=True)
    retry_count = fields.Integer(string='Số lần thử', default=0, readonly=True)

    def action_retry(self):
        """Thử gửi lại các mục thất bại."""
        to_retry = self.filtered(lambda q: q.status == 'failed')
        if not to_retry:
            raise UserError('Chỉ có thể thử lại các mục có trạng thái Thất bại.')
        for q in to_retry:
            q.invoice_id.with_context(
                meinvoice_mail_queue_id=q.id,
            )._send_meinvoice_mail(mode=q.mode, raise_on_error=False)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Thử lại gửi email',
                'message': 'Đã xử lý %d mục. Kiểm tra cột Trạng thái để xem kết quả.' % len(to_retry),
                'type': 'info',
                'sticky': False,
            },
        }

    def action_skip(self):
        """Đánh dấu bỏ qua thủ công."""
        self.filtered(lambda q: q.status in ('pending', 'failed')).write({
            'status': 'skipped',
            'reason': 'Bỏ qua thủ công',
        })
