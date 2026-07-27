# -*- coding: utf-8 -*-
import hashlib
import json
import logging
from datetime import timedelta

from odoo import api, fields, models

from odoo.addons.shopee_order_fetch.services import (
    shopee_api,
    shopee_order_builder,
)


_logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 20
PROCESSING_STALE_MINUTES = 15
RETRY_DELAYS_SECONDS = (
    60,
    300,
    900,
    1800,
    3600,
    10800,
)


class ShopeeWebhookEvent(models.Model):
    """Persistent queue for Shopee pushes that must be ACKed immediately."""

    _name = 'shopee.webhook.event'
    _description = 'Hàng đợi Shopee Webhook'
    _order = 'create_date desc, id desc'
    _rec_name = 'order_sn'

    event_key = fields.Char(required=True, index=True, readonly=True)
    code = fields.Char(string='Push Code', required=True, index=True, readonly=True)
    shop_id_raw = fields.Char(string='Shop ID', index=True, readonly=True)
    order_sn = fields.Char(string='Mã đơn Shopee', index=True, readonly=True)
    package_number = fields.Char(string='Mã kiện hàng', index=True, readonly=True)
    tracking_no = fields.Char(string='Mã vận đơn', index=True, readonly=True)
    push_timestamp = fields.Char(string='Push Timestamp', readonly=True)
    raw_payload = fields.Text(string='Payload', required=True, readonly=True)

    state = fields.Selection(
        [
            ('pending', 'Chờ xử lý'),
            ('processing', 'Đang xử lý'),
            ('done', 'Hoàn thành'),
            ('error', 'Hết lượt thử'),
        ],
        default='pending',
        required=True,
        index=True,
    )
    attempts = fields.Integer(string='Số lần thử', default=0, readonly=True)
    next_attempt_at = fields.Datetime(
        string='Thử lại lúc',
        default=fields.Datetime.now,
        index=True,
        readonly=True,
    )
    last_error = fields.Text(string='Lỗi gần nhất', readonly=True)
    result_note = fields.Text(string='Kết quả', readonly=True)
    processed_at = fields.Datetime(string='Xử lý lúc', readonly=True)
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Đơn hàng',
        ondelete='set null',
        index=True,
        readonly=True,
    )
    picking_id = fields.Many2one(
        'stock.picking',
        string='Phiếu kho',
        ondelete='set null',
        index=True,
        readonly=True,
    )

    _sql_constraints = [
        (
            'shopee_webhook_event_key_uniq',
            'unique(event_key)',
            'Shopee webhook event này đã được ghi nhận.',
        ),
    ]

    @api.model
    def _tracking_event_key(self, payload):
        """Deduplicate Shopee retries while preserving later real updates."""
        data = payload.get('data') or {}
        identity = '|'.join(
            str(value or '')
            for value in (
                payload.get('code'),
                payload.get('shop_id'),
                payload.get('timestamp'),
                data.get('ordersn'),
                data.get('package_number'),
                data.get('tracking_no'),
            )
        )
        return hashlib.sha256(identity.encode('utf-8')).hexdigest()

    @api.model
    def enqueue_tracking_push(self, payload):
        """Persist one valid code=4 push and wake the queue cron."""
        data = payload.get('data') or {}
        event_key = self._tracking_event_key(payload)
        event = self.sudo().search([('event_key', '=', event_key)], limit=1)
        if not event:
            vals = {
                'event_key': event_key,
                'code': str(payload.get('code') or ''),
                'shop_id_raw': str(payload.get('shop_id') or ''),
                'order_sn': str(data.get('ordersn') or ''),
                'package_number': str(data.get('package_number') or ''),
                'tracking_no': str(data.get('tracking_no') or ''),
                'push_timestamp': str(payload.get('timestamp') or ''),
                'raw_payload': json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(',', ':'),
                ),
                'state': 'pending',
                'next_attempt_at': fields.Datetime.now(),
            }
            try:
                with self.env.cr.savepoint():
                    event = self.sudo().create(vals)
            except Exception:
                # A concurrent Shopee retry may have inserted the same event.
                event = self.sudo().search([('event_key', '=', event_key)], limit=1)
                if not event:
                    raise

        if event.state == 'error':
            event.sudo().write({
                'state': 'pending',
                'attempts': 0,
                'next_attempt_at': fields.Datetime.now(),
                'last_error': False,
            })

        cron = self.env.ref(
            'shopee_webhook.ir_cron_process_webhook_events',
            raise_if_not_found=False,
        )
        if cron:
            cron.sudo()._trigger()
        return event

    @api.model
    def _cron_process_pending(self, limit=20):
        """Claim and process queued pushes outside the callback request."""
        stale_before = fields.Datetime.now() - timedelta(
            minutes=PROCESSING_STALE_MINUTES
        )
        stale = self.sudo().search([
            ('state', '=', 'processing'),
            ('write_date', '<', stale_before),
        ])
        if stale:
            stale.write({
                'state': 'pending',
                'next_attempt_at': fields.Datetime.now(),
                'last_error': 'Worker trước bị gián đoạn; tự động đưa về hàng đợi.',
            })
            self.env.cr.commit()

        import odoo

        processed = 0
        for _index in range(limit):
            with odoo.registry(self.env.cr.dbname).cursor() as cr:
                env = odoo.api.Environment(cr, self.env.uid, {})
                cr.execute(
                    """
                    SELECT id
                      FROM shopee_webhook_event
                     WHERE state = 'pending'
                       AND attempts < %s
                       AND (next_attempt_at IS NULL OR next_attempt_at <= %s)
                     ORDER BY create_date ASC, id ASC
                     LIMIT 1
                     FOR UPDATE SKIP LOCKED
                    """,
                    (MAX_ATTEMPTS, fields.Datetime.now()),
                )
                row = cr.fetchone()
                if not row:
                    break

                event = env['shopee.webhook.event'].sudo().browse(row[0])
                event.write({
                    'state': 'processing',
                    'attempts': event.attempts + 1,
                    'last_error': False,
                })
                cr.commit()

                try:
                    with cr.savepoint():
                        result = event._process_tracking_push()
                except Exception as exc:
                    event._schedule_retry(exc)
                    _logger.exception(
                        'Shopee webhook event %s failed (attempt %s/%s)',
                        event.id,
                        event.attempts,
                        MAX_ATTEMPTS,
                    )
                else:
                    if result.get('retry_error'):
                        event.write({
                            'sale_order_id': result.get('sale_order_id') or False,
                            'picking_id': result.get('picking_id') or False,
                        })
                        event._schedule_retry(result['retry_error'])
                        _logger.warning(
                            'Shopee webhook event %s deferred: %s',
                            event.id,
                            result['retry_error'],
                        )
                    else:
                        event.write({
                            'state': 'done',
                            'last_error': False,
                            'result_note': result.get('note') or False,
                            'sale_order_id': result.get('sale_order_id') or False,
                            'picking_id': result.get('picking_id') or False,
                            'processed_at': fields.Datetime.now(),
                        })
                cr.commit()
                processed += 1

        if processed:
            _logger.info('Shopee webhook queue processed %s event(s).', processed)

    def _schedule_retry(self, error):
        self.ensure_one()
        error_text = str(error)[:4000]
        exhausted = self.attempts >= MAX_ATTEMPTS
        delay_index = min(
            max(self.attempts - 1, 0),
            len(RETRY_DELAYS_SECONDS) - 1,
        )
        next_attempt_at = (
            False
            if exhausted
            else fields.Datetime.now()
            + timedelta(seconds=RETRY_DELAYS_SECONDS[delay_index])
        )
        self.sudo().write({
            'state': 'error' if exhausted else 'pending',
            'next_attempt_at': next_attempt_at,
            'last_error': error_text,
            'processed_at': fields.Datetime.now() if exhausted else False,
        })

    def _process_tracking_push(self):
        self.ensure_one()
        payload = json.loads(self.raw_payload)
        data = payload.get('data') or {}
        order_sn = data.get('ordersn')
        tracking_no = data.get('tracking_no')
        package_number = data.get('package_number')
        shop_id_raw = payload.get('shop_id')

        if not order_sn or not tracking_no or not shop_id_raw:
            raise ValueError(
                'Payload code=4 thiếu ordersn, tracking_no hoặc shop_id.'
            )

        shop = self.env['shopee.shop'].sudo().search(
            [('shop_identifier', '=', str(shop_id_raw))],
            limit=1,
        )
        if not shop:
            raise ValueError('Không tìm thấy Shopee shop_id=%s.' % shop_id_raw)

        candidate_orders = self.env['sale.order'].sudo().search([
            ('shopee_order_ref', '=', order_sn),
        ])
        same_shop_orders = candidate_orders.filtered(
            lambda order: order.shopee_shop_id == shop
        )
        unassigned_shop_orders = candidate_orders.filtered(
            lambda order: not order.shopee_shop_id
        )
        orders = same_shop_orders or unassigned_shop_orders
        if candidate_orders and not orders:
            raise ValueError(
                'Đơn %s tồn tại nhưng không thuộc shop_id=%s.'
                % (order_sn, shop_id_raw)
            )

        fetched_now = not orders
        if fetched_now:
            orders = self._fetch_missing_order(shop, order_sn)
        if not orders:
            raise ValueError('Chưa tìm thấy/tạo được đơn Shopee %s.' % order_sn)

        # If a previous attempt persisted a draft order without pickings, retry
        # confirmation here. A newly fetched order was already confirmed once
        # by the builder, so do not repeat the same failing call immediately.
        if not fetched_now:
            for order in orders.filtered(
                lambda current: current.state in ('draft', 'sent')
                and not current.picking_ids
            ):
                try:
                    with self.env.cr.savepoint():
                        order.sudo().action_confirm()
                except Exception as exc:
                    raise ValueError(
                        'Chưa xác nhận được đơn %s để tạo picking: %s'
                        % (order.name, exc)
                    ) from exc

        updated, matched, duplicate = self._update_tracking_number(
            orders,
            tracking_no,
            package_number=package_number,
        )
        if not matched:
            return {
                'retry_error': (
                    'Đơn %s chưa có phiếu PICK/outgoing để gắn mã vận đơn.'
                    % order_sn
                ),
                'sale_order_id': orders[:1].id,
            }

        picking = matched[:1]
        if updated:
            note = 'Đã gắn mã vận đơn %s vào %s.' % (
                tracking_no,
                ', '.join(updated.mapped('name')),
            )
        else:
            note = 'Mã vận đơn %s đã có sẵn trên phiếu %s.' % (
                tracking_no,
                picking.name,
            )
        if duplicate:
            note += (
                ' Giữ nguyên tên phiếu vì mã này đang là tên của phiếu %s.'
                % duplicate.name
            )
        return {
            'note': note,
            'sale_order_id': orders[:1].id,
            'picking_id': picking.id,
        }

    def _fetch_missing_order(self, shop, order_sn):
        status_code, body, _params, creds = (
            shopee_api.call_order_detail_with_token_refresh(shop, order_sn)
        )
        if status_code != 200 or body.get('error'):
            raise ValueError(
                'Shopee get_order_detail lỗi cho %s: %s - %s'
                % (
                    order_sn,
                    body.get('error') or 'HTTP %s' % status_code,
                    body.get('message') or '',
                )
            )

        order_list = body.get('response', {}).get('order_list') or []
        if not order_list:
            raise ValueError(
                'Shopee get_order_detail không trả dữ liệu cho %s.' % order_sn
            )

        escrow_data = shopee_api.call_escrow_detail(creds, order_sn)
        order = shopee_order_builder.create_order_from_data(
            self.env,
            order_list[0],
            shop,
            escrow_data=escrow_data,
        )
        _logger.info(
            'Shopee webhook queue auto-fetched order %s -> %s.',
            order_sn,
            order.name,
        )
        return order

    def _update_tracking_number(self, orders, tracking_no, package_number=None):
        """Apply tracking data without making a transient condition fail the push."""
        Picking = self.env['stock.picking'].sudo()
        updated_pickings = Picking
        matched_pickings = Picking
        duplicate_name_picking = Picking

        for order in orders:
            pick_pickings = order.picking_ids.sudo().filtered(
                lambda picking: 'PICK' in (
                    picking.picking_type_id.sequence_code or ''
                ).upper() and picking.state != 'cancel'
            )
            outgoing_pickings = order.picking_ids.sudo().filtered(
                lambda picking: picking.picking_type_code == 'outgoing'
                and picking.state != 'cancel'
            )

            active_pickings = pick_pickings.filtered(
                lambda picking: picking.state != 'done'
            )
            active_outgoing = outgoing_pickings.filtered(
                lambda picking: picking.state != 'done'
            )
            candidates = (
                active_pickings
                or active_outgoing
                or pick_pickings
                or outgoing_pickings
            ).sorted('id')

            already_matching = candidates.filtered(
                lambda picking: picking.carrier_tracking_ref == tracking_no
            )
            empty_candidates = candidates.filtered(
                lambda picking: not picking.carrier_tracking_ref
            )
            target = (already_matching or empty_candidates or candidates)[:1]
            matched_pickings |= target
            if not target:
                continue

            vals = {}
            if target.carrier_tracking_ref != tracking_no:
                vals['carrier_tracking_ref'] = tracking_no
            if target.name != tracking_no:
                duplicate = Picking.search([
                    ('id', '!=', target.id),
                    ('company_id', '=', target.company_id.id),
                    ('name', '=', tracking_no),
                ], limit=1)
                if duplicate:
                    duplicate_name_picking |= duplicate
                else:
                    vals['name'] = tracking_no

            if vals:
                old_name = target.name
                target.write(vals)
                updated_pickings |= target
                _logger.info(
                    'Shopee webhook queue updated order=%s picking=%s tracking=%s '
                    'package=%s.',
                    order.name,
                    old_name,
                    tracking_no,
                    package_number or '',
                )

        return updated_pickings, matched_pickings, duplicate_name_picking

    def action_retry(self):
        for event in self:
            event.sudo().write({
                'state': 'pending',
                'attempts': 0,
                'next_attempt_at': fields.Datetime.now(),
                'last_error': False,
                'processed_at': False,
            })
        cron = self.env.ref(
            'shopee_webhook.ir_cron_process_webhook_events',
            raise_if_not_found=False,
        )
        if cron:
            cron.sudo()._trigger()
        return True
