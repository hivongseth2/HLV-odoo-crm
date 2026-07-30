# -*- coding: utf-8 -*-
import json
import logging
import pytz
from datetime import datetime

from odoo import api, fields, models
from odoo.exceptions import UserError

from .amis_sync_exceptions import MeInvoiceDuplicateRefError

_logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3


class AmisWebhookQueue(models.Model):
    """
    Hàng đợi webhook Shopee → phát hành HĐĐT meInvoice.

    Khi webhook cập nhật shopee_order_status lên một trạng thái được cấu hình
    (vd: COMPLETED), một bản ghi pending sẽ được tạo ở đây.
    Cron `_process_pending` chạy định kỳ, lấy lần lượt từng bản ghi và gọi
    `action_publish_meinvoice_invoice()` trên sale.order tương ứng.
    """

    _name = 'amis.webhook.queue'
    _description = 'Hàng đợi Webhook Shopee → meInvoice Publish'
    _order = 'create_date asc'
    _rec_name = 'order_ref'

    order_ref = fields.Char(
        string='Mã đơn Shopee', index=True,
        help='shopee_order_ref của đơn hàng kích hoạt webhook.',
    )
    sale_order_id = fields.Many2one(
        'sale.order', string='Đơn hàng', ondelete='set null', index=True,
    )
    shop_id_raw = fields.Char(string='Shop ID (raw)')
    push_code = fields.Char(string='Push Code')
    trigger_status = fields.Char(
        string='Trạng thái kích hoạt',
        help='Giá trị shopee_order_status khi bản ghi này được tạo.',
    )
    raw_payload = fields.Text(string='Payload raw (JSON)')

    state = fields.Selection(
        [
            ('pending', 'Chờ xử lý'),
            ('processing', 'Đang xử lý'),
            ('deferred', 'Ngoài khung giờ'),
            ('done', 'Hoàn thành'),
            ('duplicate', 'Nghi trùng HĐ - cần đối soát'),
            ('error', 'Lỗi'),
            ('skipped', 'Bỏ qua'),
        ],
        string='Trạng thái', default='pending', required=True, index=True,
    )
    attempts = fields.Integer(string='Số lần thử', default=0)
    error_msg = fields.Text(string='Lỗi gần nhất', readonly=True)
    attempt_history = fields.Text(
        string='Lịch sử xử lý',
        readonly=True,
        copy=False,
        help='Lưu từng lần phát hành, RefID và lỗi để không mất nguyên nhân sau khi retry thành công.',
    )
    last_attempt_at = fields.Datetime(string='Lần thử cuối', readonly=True, copy=False)
    last_attempt_ref_id = fields.Char(string='RefID lần thử cuối', readonly=True, copy=False)
    processed_at = fields.Datetime(string='Xử lý lúc', readonly=True)
    meinvoice_invoice_id = fields.Many2one(
        'meinvoice.invoice', string='Hóa đơn đã phát hành', readonly=True,
    )

    # ── Cron entry point ─────────────────────────────────────────────────────

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _attempt_invoice_and_ref(self):
        self.ensure_one()
        invoice = self.meinvoice_invoice_id
        if not invoice and self.sale_order_id:
            invoice = self.env['meinvoice.invoice'].sudo().search([
                ('sale_order_id', '=', self.sale_order_id.id),
            ], order='id desc', limit=1)
        ref_id = ''
        if invoice and invoice.invoice_data_json:
            try:
                payload = json.loads(invoice.invoice_data_json)
            except Exception:
                payload = {}
            if isinstance(payload, dict):
                ref_id = (payload.get('RefID') or '').strip()
        if not ref_id and self.sale_order_id:
            ref_id = (self.sale_order_id.misa_meinvoice_ref_id or '').strip()
        return invoice, ref_id

    def _append_attempt_history(self, event, message=''):
        self.ensure_one()
        invoice, ref_id = self._attempt_invoice_and_ref()
        now = fields.Datetime.now()
        line = (
            '[%s] attempt=%s event=%s ref_id=%s invoice_id=%s message=%s'
            % (
                fields.Datetime.to_string(now),
                self.attempts,
                event,
                ref_id or '-',
                invoice.id if invoice else '-',
                ' '.join(str(message or '').split())[:1000] or '-',
            )
        )
        history = '\n'.join(filter(None, [self.attempt_history or '', line]))
        self.sudo().write({
            'attempt_history': history[-12000:],
            'last_attempt_at': now,
            'last_attempt_ref_id': ref_id or False,
        })
        return line

    @api.model
    def _format_float_time(self, value):
        """Chuyển 16.5 → '16:30' để hiển thị trong thông báo."""
        hours = int(value)
        minutes = int(round((value - hours) * 60))
        return '%02d:%02d' % (hours, minutes)

    @api.model
    def _is_within_publish_window(self, config):
        """Kiểm tra giờ hiện tại (timezone công ty) có trong khung giờ cấu hình không.
        Trả về False nếu là Chủ nhật hoặc ngoài khung giờ.
        """
        if not config.webhook_publish_time_restrict:
            return True
        tz_name = (self.env.company.partner_id.tz
                   or self.env.user.tz
                   or 'Asia/Ho_Chi_Minh')
        tz = pytz.timezone(tz_name)
        now_local = datetime.now(tz)
        # Bỏ qua Chủ nhật (isoweekday() == 7)
        if now_local.isoweekday() == 7:
            return False
        current_hour = now_local.hour + now_local.minute / 60.0
        return config.webhook_publish_time_from <= current_hour < config.webhook_publish_time_to

    # ── Cron entry point ─────────────────────────────────────────────────────

    @api.model
    def _process_pending(self):
        """
        Xử lý tối đa 20 bản ghi pending/error (còn dưới MAX_ATTEMPTS lần thử).
        Nếu bật giới hạn khung giờ và hiện đang ngoài khung:
          - Chuyển tất cả pending → deferred.
        Nếu đang trong khung giờ:
          - Nếu action=auto: reset deferred → pending rồi xử lý.
        Gọi bởi ir.cron.
        """
        config = self.env['amis.callback.config'].sudo().search([], limit=1)
        if not config or not config.webhook_auto_publish_enabled:
            return

        within_window = self._is_within_publish_window(config)

        if config.webhook_publish_time_restrict and not within_window:
            # Ngoài khung giờ: chuyển tất cả pending + error (chưa hết lượt) → deferred
            to_defer = self.sudo().search([
                ('state', 'in', ('pending', 'error')),
                ('attempts', '<', MAX_ATTEMPTS),
            ])
            if to_defer:
                time_from = self._format_float_time(config.webhook_publish_time_from)
                time_to = self._format_float_time(config.webhook_publish_time_to)
                msg = 'Ngoài khung giờ phát hành (%s – %s). ' % (time_from, time_to)
                if config.webhook_publish_deferred_action == 'auto':
                    msg += 'Sẽ tự động xử lý khi vào khung giờ.'
                else:
                    msg += 'Vui lòng bấm Thử lại thủ công khi sẵn sàng.'
                to_defer.sudo().write({'state': 'deferred', 'error_msg': msg})
                _logger.info(
                    'WebhookQueue: Ngoài khung giờ — %d đơn chuyển sang deferred.', len(to_defer)
                )
            return

        # Đang trong khung giờ (hoặc không giới hạn)
        if config.webhook_publish_time_restrict and config.webhook_publish_deferred_action == 'auto':
            # Reset các đơn deferred về pending để xử lý
            deferred = self.sudo().search([('state', '=', 'deferred')])
            if deferred:
                deferred.sudo().write({'state': 'pending', 'error_msg': False})
                _logger.info(
                    'WebhookQueue: Vào khung giờ — reset %d đơn deferred về pending.', len(deferred)
                )

        pending = self.sudo().search([
            ('state', 'in', ('pending', 'error')),
            ('attempts', '<', MAX_ATTEMPTS),
        ], limit=20)

        for item in pending:
            item._process_one(config)

    def _process_one(self, config):
        """Xử lý 1 bản ghi queue. Gọi action_publish_meinvoice_invoice trên SO."""
        self.ensure_one()
        self.sudo().write({'state': 'processing', 'attempts': self.attempts + 1})
        self._append_attempt_history('START')

        try:
            so = self.sale_order_id
            if not so:
                # Thử tìm lại theo order_ref
                so = self.env['sale.order'].sudo().search(
                    [('shopee_order_ref', '=', self.order_ref)], limit=1
                )
                if so:
                    self.sudo().write({'sale_order_id': so.id})

            if not so:
                self._append_attempt_history(
                    'SKIPPED', 'Không tìm thấy sale.order: %s' % self.order_ref,
                )
                self.sudo().write({
                    'state': 'error',
                    'error_msg': 'Không tìm thấy sale.order với mã Shopee: %s' % self.order_ref,
                })
                return

            if so.state not in ('sale', 'done'):
                self._append_attempt_history(
                    'SKIPPED', 'Đơn hàng chưa xác nhận (state=%s)' % so.state,
                )
                self.sudo().write({
                    'state': 'skipped',
                    'error_msg': 'Đơn hàng chưa xác nhận (state=%s).' % so.state,
                    'processed_at': fields.Datetime.now(),
                })
                return

            # Kiểm tra đã có hóa đơn chưa phải nháp rồi → skip
            published = self.env['meinvoice.invoice'].sudo().search([
                ('sale_order_id', '=', so.id),
                ('state', 'not in', ('draft', 'cancelled')),
            ], limit=1)
            if published:
                self._append_attempt_history(
                    'SKIPPED', 'Đã có HĐĐT id=%s state=%s' % (published.id, published.state),
                )
                self.sudo().write({
                    'state': 'skipped',
                    'error_msg': 'Đã có HĐĐT ở trạng thái %s.' % published.state,
                    'meinvoice_invoice_id': published.id,
                    'processed_at': fields.Datetime.now(),
                })
                return

            # Tìm nháp hiện có
            drafts = self.env['meinvoice.invoice'].sudo().search([
                ('sale_order_id', '=', so.id),
                ('state', '=', 'draft'),
            ], order='id desc')

            if not drafts:
                self._append_attempt_history('SKIPPED', 'Không có HĐĐT nháp để phát hành')
                self.sudo().write({
                    'state': 'skipped',
                    'error_msg': 'Không có HĐĐT nháp để phát hành.',
                    'processed_at': fields.Datetime.now(),
                })
                return

            if len(drafts) > 1:
                ids_str = ', '.join(str(d.id) for d in drafts)
                self._append_attempt_history(
                    'ERROR', 'Có nhiều HĐĐT nháp: %s' % ids_str,
                )
                self.sudo().write({
                    'state': 'error',
                    'error_msg': 'Có %d HĐĐT nháp (id: %s). Vui lòng xóa bớt và chỉ giữ 1 nháp.' % (len(drafts), ids_str),
                    'processed_at': fields.Datetime.now(),
                })
                return

            draft = drafts[0]

            # Cập nhật inv_date về ngày hôm nay (giờ địa phương) trước khi gửi CQT.
            # CQT yêu cầu InvDate = ngày gửi thực tế; nếu dùng ngày tạo nháp cũ
            # sẽ bị lỗi InvalidInvoiceDate.
            tz_name = (self.env.company.partner_id.tz
                       or self.env.user.tz
                       or 'Asia/Ho_Chi_Minh')
            today_local = datetime.now(pytz.timezone(tz_name)).date()
            if draft.inv_date != today_local:
                draft.sudo().write({'inv_date': today_local})

            # Submit nháp lên CQT
            draft.sudo().action_publish()

            self._append_attempt_history(
                'DONE',
                'inv_no=%s inv_code=%s transaction=%s'
                % (draft.inv_no or '', draft.inv_code or '', draft.transaction_id or ''),
            )
            self.sudo().write({
                'state': 'done',
                'error_msg': False,
                'meinvoice_invoice_id': draft.id,
                'processed_at': fields.Datetime.now(),
            })
            _logger.info(
                'WebhookQueue [%d]: published meInvoice for SO %s (order_ref=%s)',
                self.id, so.name, self.order_ref,
            )

        except MeInvoiceDuplicateRefError as e:
            err = str(e)
            self._append_attempt_history('DUPLICATE_REF_STOPPED', err)
            _logger.error(
                'WebhookQueue [%d]: duplicate RefID stopped for order_ref=%s: %s',
                self.id, self.order_ref, err,
            )
            self.sudo().write({
                'state': 'duplicate',
                'error_msg': err,
                'processed_at': fields.Datetime.now(),
            })

        except Exception as e:
            err = str(e)
            self._append_attempt_history('ERROR', err)
            _logger.error(
                'WebhookQueue [%d]: error publishing for order_ref=%s: %s',
                self.id, self.order_ref, err,
            )
            self.sudo().write({
                'state': 'error',
                'error_msg': err,
                'processed_at': fields.Datetime.now(),
            })

    # ── Manual actions ────────────────────────────────────────────────────────

    def action_retry(self):
        """Thử lại thủ công (kể cả đơn deferred)."""
        duplicate = self.filtered(lambda rec: rec.state == 'duplicate')
        if duplicate:
            raise UserError(
                'Không thể retry queue nghi trùng hóa đơn: %s. '
                'Phải đối soát RefID/hóa đơn trên meInvoice trước.'
                % ', '.join(duplicate.mapped('order_ref'))
            )
        for rec in self:
            rec._append_attempt_history('MANUAL_RETRY')
            rec.sudo().write({'state': 'pending', 'attempts': 0, 'error_msg': False})

    def action_skip(self):
        """Bỏ qua thủ công."""
        for rec in self:
            rec.sudo().write({'state': 'skipped', 'processed_at': fields.Datetime.now()})
