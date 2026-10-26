# -*- coding: utf-8 -*-
"""Đẩy đơn quà tặng Loyalty sang MISA dưới dạng phiếu xuất kho khác.

Đơn bán thường đi CRM → MISA → Odoo nên MISA đã có chứng từ. Riêng đơn quà tặng
sinh ra trong Odoo (nhập mã voucher Quà tặng) nên MISA không biết món quà đã ra
khỏi kho. Chỉ đẩy phiếu xuất kho loại "Khác" (reftype 2022), giá vốn ghi chi phí
khuyến mãi (6422) — không đẩy chứng từ bán hàng vì đơn quà không có doanh thu;
kế toán lập hoá đơn 0đ cho hàng khuyến mại từ phiếu xuất này trên MISA.
"""
import logging
import uuid
from datetime import datetime

from odoo import fields, models
from odoo.exceptions import UserError

from .amis_callback_utils import misa_error_means_voucher_created

_logger = logging.getLogger(__name__)

# reftype "Xuất kho khác" trong danh sách loại chứng từ AMIS kế toán (ACT Open API);
# trên MISA là phiếu xuất kho loại "4. Khác (Xuất sử dụng, góp vốn, ...)".
MISA_REFTYPE_OUTWARD_OTHER = 2022
# Đã có đề nghị/chứng từ trên MISA: không gửi lại, tránh trùng
MISA_GIFT_STATES_IN_FLIGHT = ('requested', 'created', 'posted')


class AmisCallbackConfigLoyaltyGift(models.Model):
    _inherit = 'amis.callback.config'

    sync_loyalty_gift_enabled = fields.Boolean(
        string='Đẩy đơn quà tặng Loyalty',
        default=False,
        help='Bật để khi giao xong đơn quà tặng Loyalty (đơn riêng 0đ, nhập mã voucher '
             'Quà tặng trong Odoo) thì đẩy phiếu xuất kho khác (hàng khuyến mại) lên '
             'MISA. Kế toán lập hoá đơn 0đ từ phiếu xuất đó trên MISA.',
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

    def action_misa_gift_resend(self):
        """Gửi lại phiếu xuất quà tặng sang MISA.

        Dùng khi kế toán đã xoá đề nghị trên MISA (MISA không báo về), đề nghị sai
        khách, hoặc đơn bị lỗi. Gửi cùng mã phiếu nên đề nghị còn trên MISA sẽ được
        sửa chứ không thêm bản mới; đã sinh chứng từ rồi thì MISA từ chối và đơn
        chỉ chuyển sang "Đã sinh chứng từ".
        """
        jobs = self.env['amis.sync.job'].sudo()
        for order in self:
            if not order._is_loyalty_gift_order():
                raise UserError('Đơn %s không phải đơn quà tặng Loyalty.' % order.name)
            if order.misa_gift_state == 'posted':
                raise UserError('Đơn %s đã ghi sổ trên MISA, không gửi lại.' % order.name)
            picking = order.picking_ids.filtered(
                lambda p: p.state == 'done' and p.picking_type_code == 'outgoing'
            )[:1]
            if not picking:
                raise UserError('Đơn %s chưa có phiếu xuất kho đã giao.' % order.name)
            order.write({'misa_gift_state': False, 'misa_gift_error': False})
            jobs.create({
                'picking_id': picking.id,
                'sale_order_id': order.id,
                'direction': 'loyalty_gift',
                'status': 'pending',
            })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Đã đưa vào hàng đợi',
                'message': 'Phiếu xuất quà tặng sẽ được gửi lại sang MISA trong ít phút.',
                'type': 'success',
                'sticky': False,
            },
        }


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
        """Được gọi bởi amis.sync.job — push phiếu xuất kho khác của quà lên MISA."""
        self.ensure_one()
        if self.state != 'done' or self.picking_type_code != 'outgoing':
            return

        sale_order = self._get_related_sales_order()
        if not sale_order or not sale_order._is_loyalty_gift_order():
            raise UserError('Phiếu %s không thuộc đơn quà tặng Loyalty.' % self.name)
        if sale_order.misa_gift_state in MISA_GIFT_STATES_IN_FLIGHT:
            _logger.info('Skip loyalty gift sync for %s: đơn %s đã có đề nghị trên MISA.',
                         self.name, sale_order.name)
            return

        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        config.ensure_sync_ready()

        moves = self.move_ids_without_package.filtered(lambda m: m.quantity > 0)
        if not moves:
            return
        self._misa_check_products_mapped(moves, sale_order.name)

        payload = self._prepare_misa_gift_outward_payload(config, sale_order, moves)
        config.push_outgoing_voucher(payload)
        sale_order.sudo().write({'misa_gift_state': 'requested', 'misa_gift_error': False})
        _logger.info(
            'Loyalty gift outward pushed for picking %s (SO %s), org_refid=%s',
            self.name, sale_order.name, payload['org_refid'],
        )

    def _prepare_misa_gift_outward_payload(self, config, sale_order, moves):
        """Phiếu xuất kho (voucher_type=8) loại Xuất kho khác, đứng riêng không gắn
        chứng từ bán hàng. Mọi dòng là hàng khuyến mại, tính theo giá vốn."""
        self.ensure_one()
        branch_id = (config.misa_branch_id or '').strip()
        stock_id = (config.misa_stock_id or '').strip()
        if not branch_id or not stock_id:
            raise UserError('Thiếu MISA Branch ID hoặc Stock ID trong cấu hình.')

        partner = sale_order.partner_id.commercial_partner_id
        account_object = config.resolve_misa_account_object(partner, sale_order=sale_order)
        account_object_id, account_object_code, account_object_name = account_object

        # Giữ refid qua các lần gửi lại để MISA sửa đúng đề nghị cũ thay vì tạo thêm
        refid = (self.misa_outward_org_refid or '').strip()
        if not refid:
            refid = str(uuid.uuid4())
            self.sudo().write({'misa_outward_org_refid': refid})

        debit_account = (config.loyalty_gift_debit_account or '').strip() or '6422'
        detail = [
            dict(
                self._misa_outward_detail_vals(
                    move, refid, idx, stock_id, account_object, debit_account=debit_account,
                ),
                is_promotion=True,  # in_outward_detail/is_promotion: "Là hàng khuyến mại"
            )
            for idx, move in enumerate(moves, start=1)
        ]
        total_cost = sum(d['amount_finance'] for d in detail)
        refdate = self._to_misa_date(self.date_done)
        receiver = self.partner_id or sale_order.partner_shipping_id

        return {
            'voucher_type': 8,
            'is_get_new_id': False,
            'org_refid': refid,
            'org_refno': self.name,
            'org_reftype': MISA_REFTYPE_OUTWARD_OTHER,
            'refid': refid,
            'reftype': MISA_REFTYPE_OUTWARD_OTHER,
            'reftype_name': 'Xuất kho khác',
            'is_allow_group': False,
            'act_voucher_type': 0,
            'branch_id': branch_id,
            'from_stock_id': stock_id,
            'account_object_id': account_object_id,
            'account_object_code': account_object_code,
            'account_object_name': account_object_name,
            'account_object_address': partner.contact_address_complete or '',
            'account_object_tax_code': partner.vat or '',
            'contact_name': receiver.name or '',
            'display_on_book': 0,
            'reforder': int(datetime.utcnow().timestamp() * 1000),
            'refdate': refdate,
            'posted_date': refdate,
            'is_posted_finance': False,
            'is_posted_management': False,
            'is_posted_inventory_book_finance': False,
            'is_posted_inventory_book_management': False,
            'is_branch_issued': False,
            'is_sale_with_outward': False,
            'is_invoice_replace': False,
            'total_amount_finance': total_cost,
            'total_amount_management': total_cost,
            'refno_finance': '',
            'refno_management': '',
            'journal_memo': 'Xuat qua tang Loyalty %s - voucher %s (Odoo: %s)' % (
                sale_order.name, sale_order.loyalty_voucher_id.code or '', self.name,
            ),
            'auto_refno': False,
            'state': 0,
            'detail': detail,
        }


class AmisCallbackLogLineLoyaltyGift(models.Model):
    _inherit = 'amis.callback.log.line'

    # model_state của callback data_type 22 (MISA báo thay đổi trên chứng từ thật)
    _GIFT_STATE_BY_MODEL_STATE = {1: 'created', 7: 'posted', 8: 'created', 3: 'deleted'}

    def _apply_sync_result(self):
        res = super()._apply_sync_result()
        pickings = self.env['stock.picking'].sudo()
        jobs = self.env['amis.sync.job'].sudo()
        for line in self:
            org_refid = (line.org_refid or '').strip()
            if not org_refid:
                continue
            picking = pickings.search([('misa_outward_org_refid', '=', org_refid)], limit=1)
            if not picking:
                continue
            # misa_outward_org_refid cũng là phiếu xuất kèm SAVoucher của đơn thường —
            # chỉ xử lý phiếu đã có job quà tặng.
            job = jobs.search([
                ('picking_id', '=', picking.id),
                ('direction', '=', 'loyalty_gift'),
            ], order='id desc', limit=1)
            if job and job.sale_order_id:
                line._apply_loyalty_gift_result(job.sale_order_id, job)
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
                # 'deleted' nằm ngoài MISA_GIFT_STATES_IN_FLIGHT nên bấm "Thử lại" trên
                # job là gửi lại được nếu kế toán xoá nhầm; không tự gửi lại.
                order.write({'misa_gift_state': state, 'misa_gift_error': False})
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
        order.write({'misa_gift_state': 'error', 'misa_gift_error': error_message})
        if is_request and data_type in (1, 3):
            job._schedule_retry_after_callback_error(error_message)
