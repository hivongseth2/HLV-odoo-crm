# -*- coding: utf-8 -*-
import json
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class SaleOrderWebhookEnqueue(models.Model):
    """
    Extend sale.order để enqueue webhook Shopee → meInvoice publish.

    Khi shopee_order_status được ghi với giá trị nằm trong danh sách
    `webhook_trigger_statuses` của config, một bản ghi `amis.webhook.queue`
    sẽ được tạo để cron xử lý sau.
    Dedup: mỗi (sale_order_id, trigger_status) chỉ tạo 1 lần (pending/done đều skip nếu done).
    """

    _inherit = 'sale.order'

    def write(self, vals):
        new_status = vals.get('shopee_order_status')
        result = super().write(vals)

        if new_status:
            self._maybe_enqueue_webhook(new_status)

        return result

    def _maybe_enqueue_webhook(self, new_status):
        """Enqueue nếu config bật và status khớp.

        Dùng savepoint để cách ly: nếu Queue.create() fail ở tầng DB,
        savepoint rollback nhưng transaction chính (đã write shopee_order_status)
        vẫn được commit bình thường.
        """
        try:
            config = self.env['amis.callback.config'].sudo().search([], limit=1)
            if not config or not config.webhook_auto_publish_enabled:
                return

            trigger_statuses = config.get_webhook_trigger_statuses()
            if new_status not in trigger_statuses:
                return

            Queue = self.env['amis.webhook.queue'].sudo()
            for so in self:
                if not getattr(so, 'shopee_order_ref', None):
                    continue  # chỉ xử lý đơn Shopee

                # Dedup: không tạo nếu đã có bản ghi pending/processing/done
                existing = Queue.search([
                    ('sale_order_id', '=', so.id),
                    ('state', 'in', ('pending', 'processing', 'done', 'skipped')),
                ], limit=1)
                if existing:
                    _logger.info(
                        'WebhookQueue: SO %s (ref=%s) đã có queue id=%d state=%s, bỏ qua.',
                        so.name, so.shopee_order_ref, existing.id, existing.state,
                    )
                    continue

                try:
                    with self.env.cr.savepoint():
                        Queue.create({
                            'order_ref': so.shopee_order_ref,
                            'sale_order_id': so.id,
                            'trigger_status': new_status,
                            'state': 'pending',
                        })
                    _logger.info(
                        'WebhookQueue: Enqueued meInvoice publish for SO %s (ref=%s, status=%s)',
                        so.name, so.shopee_order_ref, new_status,
                    )
                except Exception as create_err:
                    _logger.error(
                        'WebhookQueue: Queue.create thất bại SO %s: %s', so.name, create_err
                    )
        except Exception as e:
            _logger.error('WebhookQueue: _maybe_enqueue_webhook error: %s', e)
