# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

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
            ('done', 'Hoàn thành'),
            ('error', 'Lỗi'),
            ('skipped', 'Bỏ qua'),
        ],
        string='Trạng thái', default='pending', required=True, index=True,
    )
    attempts = fields.Integer(string='Số lần thử', default=0)
    error_msg = fields.Text(string='Lỗi gần nhất', readonly=True)
    processed_at = fields.Datetime(string='Xử lý lúc', readonly=True)
    meinvoice_invoice_id = fields.Many2one(
        'meinvoice.invoice', string='Hóa đơn đã phát hành', readonly=True,
    )

    # ── Cron entry point ─────────────────────────────────────────────────────

    @api.model
    def _process_pending(self):
        """
        Xử lý tối đa 20 bản ghi pending/error (còn dưới MAX_ATTEMPTS lần thử).
        Gọi bởi ir.cron.
        """
        config = self.env['amis.callback.config'].sudo().search([], limit=1)
        if not config or not config.webhook_auto_publish_enabled:
            return

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
                self.sudo().write({
                    'state': 'error',
                    'error_msg': 'Không tìm thấy sale.order với mã Shopee: %s' % self.order_ref,
                })
                return

            if so.state not in ('sale', 'done'):
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
                self.sudo().write({
                    'state': 'skipped',
                    'error_msg': 'Đã có HĐĐT ở trạng thái %s.' % published.state,
                    'meinvoice_invoice_id': published.id,
                    'processed_at': fields.Datetime.now(),
                })
                return

            # Gọi action publish (tạo draft + publish luôn qua SO method)
            so.sudo().action_publish_meinvoice_invoice()

            # Tìm invoice vừa tạo (state submitted/accepted)
            new_inv = self.env['meinvoice.invoice'].sudo().search([
                ('sale_order_id', '=', so.id),
                ('state', 'in', ('submitted', 'accepted')),
            ], limit=1)

            self.sudo().write({
                'state': 'done',
                'error_msg': False,
                'meinvoice_invoice_id': new_inv.id if new_inv else False,
                'processed_at': fields.Datetime.now(),
            })
            _logger.info(
                'WebhookQueue [%d]: published meInvoice for SO %s (order_ref=%s)',
                self.id, so.name, self.order_ref,
            )

        except Exception as e:
            err = str(e)
            _logger.error(
                'WebhookQueue [%d]: error publishing for order_ref=%s: %s',
                self.id, self.order_ref, err,
            )
            new_state = 'error' if self.attempts < MAX_ATTEMPTS else 'error'
            self.sudo().write({'state': new_state, 'error_msg': err})

    # ── Manual actions ────────────────────────────────────────────────────────

    def action_retry(self):
        """Thử lại thủ công."""
        for rec in self:
            rec.sudo().write({'state': 'pending', 'attempts': 0, 'error_msg': False})

    def action_skip(self):
        """Bỏ qua thủ công."""
        for rec in self:
            rec.sudo().write({'state': 'skipped', 'processed_at': fields.Datetime.now()})
