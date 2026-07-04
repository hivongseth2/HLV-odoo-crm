# -*- coding: utf-8 -*-
"""
Cron mỗi 3 tiếng: tự chủ động hỏi lại Shopee trạng thái các đơn hàng
chưa ở trạng thái kết thúc (chưa Hoàn thành, chưa Hủy).

Mục đích: bù đắp trường hợp webhook Shopee bị lỡ (Shopee chỉ gửi 1 lần).
Khi cập nhật shopee_order_status, `amis_callback` sẽ tự enqueue job
phát hành HĐĐT meInvoice nếu trạng thái khớp trigger.
"""
import logging
from datetime import timedelta

from odoo import api, fields, models

from odoo.addons.shopee_order_fetch.services import shopee_api

_logger = logging.getLogger(__name__)

# Trạng thái Shopee kết thúc (không cần poll nữa)
_TERMINAL_STATUSES = frozenset({
    'COMPLETED', 'Hoàn thành',
    'CANCELLED', 'Đã hủy', 'Đã Hủy',
})

# Map English code → Vietnamese name (đồng bộ với webhook controller)
_STATUS_MAP = {
    'UNPAID': 'Chưa thanh toán',
    'READY_TO_SHIP': 'Chờ lấy hàng',
    'PROCESSED': 'Đã xử lý',
    'SHIPPED': 'Đang giao',
    'COMPLETED': 'Hoàn thành',
    'IN_CANCEL': 'Chờ xác nhận hủy',
    'CANCELLED': 'Đã hủy',
    'RETRY_SHIP': 'Giao lại',
    'TO_CONFIRM_RECEIVE': 'Đã nhận hàng',
    'TO_RETURN': 'Đang trả hàng',
}

# Shopee API giới hạn 50 mã/lần gọi
_BATCH_SIZE = 50

# Không poll đơn cũ hơn N ngày (tránh tốn API quota cho đơn đã cũ)
_MAX_AGE_DAYS = 60


class SaleOrderStatusPoll(models.Model):
    """Mixin thêm cron poll trạng thái Shopee vào sale.order."""

    _inherit = 'sale.order'

    @api.model
    def _cron_poll_shopee_order_status(self):
        """
        Cron entry point — chạy mỗi 3 tiếng.

        1. Tìm tất cả đơn Shopee chưa ở trạng thái kết thúc.
        2. Group theo shopee_shop_id.
        3. Với mỗi shop, gọi Shopee API get_order_detail theo batch 50 đơn.
        4. Cập nhật shopee_order_status → kích hoạt _maybe_enqueue_webhook.
        5. Ghi log vào shopee.poll.log để theo dõi.
        """
        cutoff = fields.Datetime.now() - timedelta(days=_MAX_AGE_DAYS)
        orders = self.sudo().search([
            ('shopee_order_ref', '!=', False),
            ('shopee_shop_id', '!=', False),
            ('shopee_order_status', 'not in', list(_TERMINAL_STATUSES)),
            ('state', '!=', 'cancel'),
            ('create_date', '>=', cutoff),
        ])

        # Tạo log record ngay từ đầu để track kể cả khi không có gì thay đổi
        PollLog = self.env['shopee.poll.log'].sudo()
        log = PollLog.create({
            'polled_at': fields.Datetime.now(),
            'total_polled': len(orders),
            'changed_count': 0,
            'state': 'done',
        })

        if not orders:
            _logger.info('ShopeeStatusPoll: không có đơn nào cần poll.')
            return

        _logger.info('ShopeeStatusPoll: cần poll %d đơn.', len(orders))

        # Group by shop để tái dùng credentials
        by_shop = {}
        for so in orders:
            shop = so.shopee_shop_id
            by_shop.setdefault(shop.id, {'shop': shop, 'orders': []})
            by_shop[shop.id]['orders'].append(so)

        total_updated = 0
        has_error = False
        log_lines = []  # collect rồi bulk-create cuối

        for shop_id, data in by_shop.items():
            shop = data['shop']
            shop_orders = data['orders']
            shop_name = shop.display_name or str(shop_id)
            try:
                creds = shopee_api.get_credentials_from_shop(shop)
            except Exception as exc:
                _logger.warning(
                    'ShopeeStatusPoll: không lấy được credentials cho shop %s: %s',
                    shop_name, exc,
                )
                has_error = True
                continue

            # Batch theo 50
            for i in range(0, len(shop_orders), _BATCH_SIZE):
                batch = shop_orders[i:i + _BATCH_SIZE]
                order_sns = ','.join(so.shopee_order_ref for so in batch)
                try:
                    status_code, body, _, _creds = shopee_api.call_order_detail_with_token_refresh(
                        shop, order_sns,
                        optional_fields='',  # chỉ lấy trường mặc định (có order_status)
                    )
                except Exception as exc:
                    _logger.warning(
                        'ShopeeStatusPoll: call_order_detail lỗi shop=%s batch=%d: %s',
                        shop_name, i // _BATCH_SIZE + 1, exc,
                    )
                    has_error = True
                    continue

                if status_code != 200 or body.get('error'):
                    _logger.warning(
                        'ShopeeStatusPoll: Shopee trả lỗi shop=%s: %s',
                        shop_name, body.get('error') or status_code,
                    )
                    has_error = True
                    continue

                order_list = body.get('response', {}).get('order_list') or []
                # Build map: order_sn → order_status
                sn_to_status = {}
                for item in order_list:
                    sn = item.get('order_sn') or item.get('ordersn') or ''
                    raw_status = (item.get('order_status') or '').upper()
                    if sn and raw_status:
                        sn_to_status[sn] = _STATUS_MAP.get(raw_status, raw_status)

                for so in batch:
                    new_status = sn_to_status.get(so.shopee_order_ref)
                    if not new_status:
                        continue
                    old_status = so.shopee_order_status or ''
                    if new_status == old_status:
                        continue
                    write_ok = True
                    note = ''
                    try:
                        so.sudo().write({'shopee_order_status': new_status})
                        total_updated += 1
                        _logger.info(
                            'ShopeeStatusPoll: SO %s %s → %s',
                            so.name, old_status or '(trống)', new_status,
                        )
                    except Exception as exc:
                        write_ok = False
                        note = str(exc)[:255]
                        has_error = True
                        _logger.warning(
                            'ShopeeStatusPoll: write thất bại SO %s: %s', so.name, exc
                        )
                    log_lines.append({
                        'log_id': log.id,
                        'sale_order_id': so.id,
                        'order_ref': so.shopee_order_ref,
                        'shop_name': shop_name,
                        'old_status': old_status or '(trống)',
                        'new_status': new_status,
                        'changed': write_ok,
                        'note': note,
                    })

        # Bulk-create lines và cập nhật tổng kết
        if log_lines:
            self.env['shopee.poll.log.line'].sudo().create(log_lines)
        log.sudo().write({
            'changed_count': total_updated,
            'state': 'partial' if has_error else 'done',
        })
        _logger.info('ShopeeStatusPoll: hoàn thành — cập nhật %d đơn.', total_updated)
