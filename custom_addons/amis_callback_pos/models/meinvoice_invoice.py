# -*- coding: utf-8 -*-
import logging
from datetime import datetime

import pytz

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.amis_callback.models.amis_sync_exceptions import MeInvoiceDuplicateRefError

_logger = logging.getLogger(__name__)

MAX_PUBLISH_ATTEMPTS = 3
PUBLISH_BATCH_SIZE = 50


class MeinvoiceInvoicePos(models.Model):
    _inherit = 'meinvoice.invoice'

    pos_order_id = fields.Many2one(
        'pos.order', string='Đơn POS', ondelete='restrict', readonly=True, index='btree_not_null',
    )
    pos_auto_publish = fields.Boolean(
        string='Chờ tự phát hành (POS)', default=False, copy=False, index=True,
        help='Cron sẽ gửi CQT hóa đơn nháp này. Tự tắt khi đã gửi, khi MISA báo '
             'trùng RefID, hoặc sau %d lần lỗi.' % MAX_PUBLISH_ATTEMPTS,
    )
    pos_publish_attempts = fields.Integer(string='Số lần thử phát hành', default=0, copy=False)
    pos_publish_error = fields.Text(string='Lỗi phát hành tự động', readonly=True, copy=False)

    @api.depends('pos_order_id.partner_id')
    def _compute_partner_id(self):
        super()._compute_partner_id()
        for rec in self.filtered('pos_order_id'):
            rec.partner_id = rec.pos_order_id.partner_id

    @api.depends('pos_order_id')
    def _compute_name(self):
        super()._compute_name()
        for rec in self.filtered(lambda r: r.pos_order_id and not r.inv_no):
            rec.name = 'Nháp — %s' % rec.pos_order_id.name

    @api.model
    def _cron_publish_pos_invoices(self):
        """Gửi CQT các hóa đơn nháp của đơn POS đang chờ tự phát hành."""
        config = self.env['amis.callback.config'].sudo().search([], limit=1)
        if not config or not config.meinvoice_pos_enabled or not config.meinvoice_pos_auto_publish:
            return
        invoices = self.sudo().search([
            ('pos_auto_publish', '=', True),
            ('state', '=', 'draft'),
            ('pos_publish_attempts', '<', MAX_PUBLISH_ATTEMPTS),
        ], order='id', limit=PUBLISH_BATCH_SIZE)
        for invoice in invoices:
            invoice._publish_pos_invoice()
            # Commit từng hóa đơn: một hóa đơn đã lên CQT mà bị rollback chung với
            # hóa đơn lỗi phía sau thì Odoo mất số HĐ, lần sau chỉ còn báo trùng RefID.
            self.env.cr.commit()

    def _publish_pos_invoice(self):
        """Gửi CQT một hóa đơn POS, ghi lại lỗi thay vì ném ra (chạy trong cron)."""
        self.ensure_one()
        attempts = self.pos_publish_attempts + 1
        self.write({'pos_publish_attempts': attempts})
        # CQT đòi InvDate = ngày gửi thực tế; nháp lỗi được thử lại sang ngày sau
        # thì phải đổi ngày, nếu không bị InvalidInvoiceDate.
        today_local = datetime.now(pytz.timezone(self._pos_timezone())).date()
        try:
            with self.env.cr.savepoint():
                if self.inv_date != today_local:
                    self.write({'inv_date': today_local})
                self.action_publish()
        except MeInvoiceDuplicateRefError as exc:
            self.write({'pos_auto_publish': False, 'pos_publish_error': str(exc)})
            _logger.error('meInvoice POS %s: dừng vì trùng RefID: %s', self.name, exc)
        except Exception as exc:
            self.write({
                'pos_auto_publish': attempts < MAX_PUBLISH_ATTEMPTS,
                'pos_publish_error': str(exc),
            })
            _logger.warning('meInvoice POS %s: phát hành lỗi lần %d: %s', self.name, attempts, exc)
        else:
            self.write({'pos_auto_publish': False, 'pos_publish_error': False})

    def _pos_timezone(self):
        return self.env.company.partner_id.tz or self.env.user.tz or 'Asia/Ho_Chi_Minh'

    def action_retry_pos_publish(self):
        """Đưa hóa đơn POS lỗi về hàng chờ tự phát hành và chạy cron ngay."""
        not_retryable = self.filtered(lambda r: not r.pos_order_id or r.state != 'draft')
        if not_retryable:
            raise UserError(
                'Chỉ thử lại được hóa đơn nháp của đơn POS: %s'
                % ', '.join(not_retryable.mapped('name'))
            )
        self.write({'pos_auto_publish': True, 'pos_publish_attempts': 0, 'pos_publish_error': False})
        self.env.ref('amis_callback_pos.ir_cron_meinvoice_pos_publish').sudo()._trigger()
        return True
