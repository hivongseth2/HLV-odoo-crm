# -*- coding: utf-8 -*-
"""Đẩy đơn quà tặng Loyalty sang MISA dưới dạng chứng từ bán hàng hàng khuyến mại.

Đơn bán thường đi CRM → MISA → Odoo nên MISA đã có chứng từ. Riêng đơn quà tặng
sinh ra trong Odoo (nhân viên nhập mã voucher Quà tặng) nên MISA không biết món
quà đã ra khỏi kho. Đẩy SAVoucher kiêm phiếu xuất (không phải phiếu xuất kho đứng
riêng) vì kế toán phải lập hoá đơn 0đ cho hàng khuyến mại từ chứng từ bán hàng
trên MISA; giá vốn ghi vào chi phí (6422) thay vì 632.
"""
import logging

from odoo import fields, models
from odoo.exceptions import UserError

from .amis_callback_utils import misa_error_means_voucher_created

_logger = logging.getLogger(__name__)


class AmisCallbackConfigLoyaltyGift(models.Model):
    _inherit = 'amis.callback.config'

    sync_loyalty_gift_enabled = fields.Boolean(
        string='Đẩy đơn quà tặng Loyalty',
        default=False,
        help='Bật để khi giao xong đơn quà tặng Loyalty (đơn riêng 0đ, nhập mã voucher '
             'Quà tặng trong Odoo) thì đẩy chứng từ bán hàng khuyến mại kiêm phiếu xuất '
             'lên MISA. Kế toán lập hoá đơn từ chứng từ đó trên MISA.',
    )
    loyalty_gift_debit_account = fields.Char(
        string='TK chi phí quà tặng',
        default='6422',
        help='Tài khoản ghi Nợ giá vốn hàng quà tặng (thay cho 632). Tài khoản kho là 1561.',
    )


class SaleOrderLoyaltyGiftMisa(models.Model):
    _inherit = 'sale.order'

    # Đẩy sang MISA chỉ là "cất đề nghị sinh chứng từ"; chứng từ thật có khi kế
    # toán sinh từ đề nghị, và chỉ tính sổ sau khi ghi sổ — nên phải theo từng bước.
    misa_gift_state = fields.Selection([
        ('requested', 'Đã gửi đề nghị, chờ kế toán sinh chứng từ'),
        ('created', 'Đã sinh chứng từ, chưa ghi sổ'),
        ('posted', 'Đã ghi sổ'),
        ('deleted', 'Chứng từ đã bị xóa trên MISA'),
        ('error', 'Lỗi'),
    ], string='Trạng thái MISA đơn quà tặng', copy=False, readonly=True)
    misa_gift_error = fields.Text(string='Lỗi MISA đơn quà tặng', copy=False, readonly=True)


class StockPickingLoyaltyGiftSync(models.Model):
    _inherit = 'stock.picking'

    def _enqueue_misa_sync(self, direction):
        self.ensure_one()
        sale_order = self._get_related_sales_order() if direction == 'outgoing' else None
        if sale_order and sale_order._is_loyalty_gift_order():
            # Đơn quà tặng không đi job outgoing thường: job đó lọc theo Shopee và
            # ghi giá vốn 632 thay vì chi phí khuyến mãi.
            self._enqueue_misa_loyalty_gift(sale_order)
            return
        return super()._enqueue_misa_sync(direction)

    def _enqueue_misa_loyalty_gift(self, sale_order):
        self.ensure_one()
        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        if not config.sync_loyalty_gift_enabled:
            return
        jobs = self.env['amis.sync.job'].sudo()
        if jobs.search_count([
            ('sale_order_id', '=', sale_order.id),
            ('direction', '=', 'loyalty_gift'),
            ('status', 'in', ('pending', 'done')),
        ]):
            return
        jobs.create({
            'picking_id': self.id,
            'sale_order_id': sale_order.id,
            'direction': 'loyalty_gift',
            'status': 'pending',
        })
        _logger.info('AMIS loyalty gift job enqueued for picking %s (SO %s)', self.name, sale_order.name)

    def _sync_loyalty_gift_to_misa(self):
        """Được gọi bởi amis.sync.job — push SAVoucher hàng khuyến mại lên MISA."""
        self.ensure_one()
        if self.state != 'done' or self.picking_type_code != 'outgoing':
            return

        sale_order = self._get_related_sales_order()
        if not sale_order or not sale_order._is_loyalty_gift_order():
            raise UserError('Phiếu %s không thuộc đơn quà tặng Loyalty.' % self.name)
        if sale_order.misa_sa_voucher_synced:
            _logger.info('Skip loyalty gift sync for %s: đơn %s đã đẩy MISA.', self.name, sale_order.name)
            return

        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        config.ensure_sync_ready()

        moves = self.move_ids_without_package.filtered(lambda m: m.quantity > 0)
        if not moves:
            return
        self._misa_check_products_mapped(moves, sale_order.name)

        payload = self._prepare_misa_gift_sa_voucher_payload(config, sale_order)
        config.push_sa_voucher(payload)
        sale_order.sudo().write({
            'misa_sa_voucher_synced': True,
            'misa_sa_voucher_org_refid': payload['org_refid'],
            'misa_gift_state': 'requested',
            'misa_gift_error': False,
        })
        _logger.info(
            'Loyalty gift SAVoucher pushed for picking %s (SO %s), org_refid=%s',
            self.name, sale_order.name, payload['org_refid'],
        )

    def _prepare_misa_gift_sa_voucher_payload(self, config, sale_order):
        """SAVoucher bán hàng kiêm xuất kho, mọi dòng là hàng khuyến mại 0đ.

        Dựng từ payload SAVoucher chung rồi chỉnh những chỗ khác của quà tặng.
        """
        self.ensure_one()
        voucher = self._prepare_misa_sa_voucher_payload(config, sale_order)
        debit_account = (config.loyalty_gift_debit_account or '').strip() or '6422'
        voucher_code = sale_order.loyalty_voucher_id.code or ''

        # Chưa lập hoá đơn: kế toán tự lập hoá đơn 0đ trên MISA. Bỏ sa_invoice_refid
        # để MISA không tìm hoá đơn kèm theo không tồn tại.
        voucher.pop('sa_invoice_refid', None)
        voucher['include_invoice'] = 0
        voucher['journal_memo'] = 'Xuat qua tang Loyalty %s - voucher %s (Odoo: %s)' % (
            sale_order.name, voucher_code, self.name,
        )
        for line in voucher['detail']:
            line.update({
                'is_promotion': True,
                'cost_account': debit_account,
                'stock_account': '1561',
            })
        outward = voucher['in_outward']
        outward['journal_memo'] = voucher['journal_memo']
        for line in outward['detail']:
            line.update({'is_promotion': True, 'debit_account': debit_account})
        return voucher


class AmisCallbackLogLineLoyaltyGift(models.Model):
    _inherit = 'amis.callback.log.line'

    # model_state của callback data_type 22 (MISA báo thay đổi trên chứng từ thật)
    _GIFT_STATE_BY_MODEL_STATE = {1: 'created', 7: 'posted', 8: 'created', 3: 'deleted'}

    def _apply_sync_result(self):
        res = super()._apply_sync_result()
        orders = self.env['sale.order'].sudo()
        jobs = self.env['amis.sync.job'].sudo()
        for line in self:
            org_refid = (line.org_refid or '').strip()
            if not org_refid:
                continue
            order = orders.search([('misa_sa_voucher_org_refid', '=', org_refid)], limit=1)
            if not order:
                continue
            job = jobs.search([
                ('sale_order_id', '=', order.id),
                ('direction', '=', 'loyalty_gift'),
            ], order='id desc', limit=1)
            if job:  # không có job là SAVoucher của đơn thường, không phải quà tặng
                line._apply_loyalty_gift_result(order, job)
        return res

    def _apply_loyalty_gift_result(self, order, job):
        self.ensure_one()
        item = self._misa_callback_item()
        data_type = int(self.log_id.data_type or 0)
        error_message = self.error_message or self.error_call_back_message or ''

        if data_type == 22:
            try:
                model_state = int(item.get('_misa_model_state') or 0)
            except (TypeError, ValueError):
                model_state = 0
            state = self._GIFT_STATE_BY_MODEL_STATE.get(model_state)
            if state:
                vals = {'misa_gift_state': state, 'misa_gift_error': False}
                if state == 'deleted':
                    # Mở lại để bấm chạy lại job nếu kế toán xóa nhầm; không tự gửi lại.
                    vals['misa_sa_voucher_synced'] = False
                order.write(vals)
            return

        is_request = self._misa_callback_is_request_callback(
            self._misa_callback_voucher_type(item), self._misa_callback_refno(item),
        )
        if self.success:
            order.write({
                'misa_gift_state': 'requested' if is_request else 'created',
                'misa_gift_error': False,
            })
            return
        if misa_error_means_voucher_created(self.error_code, error_message):
            # Gửi lại đề nghị cho đơn mà kế toán đã sinh chứng từ: không phải lỗi.
            order.write({'misa_gift_state': 'created', 'misa_gift_error': False})
            return
        order.write({
            'misa_sa_voucher_synced': False,
            'misa_gift_state': 'error',
            'misa_gift_error': error_message,
        })
        if is_request and data_type in (1, 3):
            job._schedule_retry_after_callback_error(error_message)
