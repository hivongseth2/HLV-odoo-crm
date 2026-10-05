# -*- coding: utf-8 -*-
import json
import logging
import re
import uuid
from datetime import datetime

import pytz

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_is_zero

from odoo.addons.amis_callback.models.meinvoice_utils import seller_fields
from .pos_meinvoice_utils import build_invoice_lines

_logger = logging.getLogger(__name__)

PAID_STATES = ('paid', 'done', 'invoiced')


class PosOrderMeinvoice(models.Model):
    _inherit = 'pos.order'

    meinvoice_invoice_ids = fields.One2many(
        'meinvoice.invoice', 'pos_order_id', string='Hóa đơn điện tử', readonly=True,
    )
    meinvoice_status = fields.Selection(
        [
            ('none', 'Chưa có'),
            ('draft', 'Nháp'),
            ('error', 'Lỗi phát hành'),
            ('published', 'Đã gửi CQT'),
        ],
        string='HĐĐT', compute='_compute_meinvoice_status',
    )
    meinvoice_review_needed = fields.Boolean(
        string='Kế toán cần xem (HĐĐT)', default=False, copy=False, index=True,
        help='Đơn không tự xuất được hóa đơn (trả/đổi hàng, lệch tiền...). Kế toán '
             'tự điều chỉnh rồi bấm "Đã xử lý".',
    )
    meinvoice_review_note = fields.Char(string='Lý do cần xem (HĐĐT)', copy=False)

    @api.depends('meinvoice_invoice_ids.state', 'meinvoice_invoice_ids.pos_publish_error')
    def _compute_meinvoice_status(self):
        for order in self:
            invoices = order.meinvoice_invoice_ids.filtered(lambda i: i.state != 'cancelled')
            if not invoices:
                order.meinvoice_status = 'none'
            elif invoices.filtered(lambda i: i.state != 'draft'):
                order.meinvoice_status = 'published'
            elif invoices.filtered('pos_publish_error'):
                order.meinvoice_status = 'error'
            else:
                order.meinvoice_status = 'draft'

    # ── Kích hoạt khi POS lưu đơn đã thanh toán ─────────────────────────────

    def _process_saved_order(self, draft):
        order_id = super()._process_saved_order(draft)
        if not draft:
            self._meinvoice_after_payment()
        return order_id

    def _meinvoice_after_payment(self):
        """Tạo nháp HĐĐT và đánh thức cron phát hành. Không bao giờ chặn lưu đơn POS."""
        config = self.env['amis.callback.config'].sudo().search([], limit=1)
        if not config or not config.meinvoice_enabled or not config.meinvoice_pos_enabled:
            return
        try:
            with self.env.cr.savepoint():
                invoice = self.sudo()._meinvoice_create_draft(config)
            if invoice and invoice.pos_auto_publish:
                self.env.ref('amis_callback_pos.ir_cron_meinvoice_pos_publish').sudo()._trigger()
        except Exception:
            _logger.exception('meInvoice POS: tạo HĐĐT nháp cho %s thất bại (bỏ qua).', self.name)

    # ── Dựng hóa đơn nháp ───────────────────────────────────────────────────

    def _meinvoice_create_draft(self, config):
        """Tạo meinvoice.invoice nháp cho đơn POS đã thanh toán.

        Trả hóa đơn vừa tạo, hoặc hóa đơn rỗng khi không tạo: đơn chưa thanh toán,
        đã có hóa đơn còn hiệu lực, hoặc đơn phải để kế toán xử lý tay (khi đó đơn
        được đánh dấu meinvoice_review_needed kèm lý do).
        """
        self.ensure_one()
        Invoice = self.env['meinvoice.invoice']
        if self.state not in PAID_STATES:
            return Invoice
        if self.meinvoice_invoice_ids.filtered(lambda i: i.state != 'cancelled'):
            return Invoice

        currency = self.currency_id
        if any(line.qty < 0 for line in self.lines):
            return self._meinvoice_flag_review('Đơn trả/đổi hàng — kế toán tự điều chỉnh hóa đơn.')
        if float_is_zero(self.amount_total, precision_rounding=currency.rounding):
            return self._meinvoice_flag_review('Đơn 0 đồng — không tự xuất hóa đơn.')

        try:
            line_vals = build_invoice_lines(self._meinvoice_line_inputs())
        except ValueError as exc:
            return self._meinvoice_flag_review(str(exc))
        if not line_vals:
            return self._meinvoice_flag_review('Đơn không có dòng hàng để xuất hóa đơn.')

        # Làm tròn tiền mặt / làm tròn thuế toàn đơn có thể khiến tổng dòng khác
        # số khách thực trả. Khi đó vẫn tạo nháp nhưng giữ lại cho kế toán.
        invoice_total = sum(v['amount_without_vat_oc'] + v['vat_amount_oc'] for v in line_vals)
        mismatch = not float_is_zero(
            invoice_total - self.amount_total, precision_rounding=currency.rounding,
        )
        hold_reason = (
            'Tổng hóa đơn {:,.0f} khác tổng đơn POS {:,.0f} — kế toán kiểm tra rồi tự gửi CQT.'
            .format(invoice_total, self.amount_total)
        ) if mismatch else False
        auto_publish = (
            config.meinvoice_pos_enabled and config.meinvoice_pos_auto_publish and not mismatch
        )

        inv_series = (config.meinvoice_inv_series or '').strip()
        if not inv_series:
            return self._meinvoice_flag_review('Thiếu ký hiệu hóa đơn trong cấu hình meInvoice.')
        inv_date = datetime.now(pytz.timezone(Invoice._pos_timezone())).date()
        buyer = self._meinvoice_buyer_vals(config)
        # Không gửi mail "bản xem trước": hóa đơn POS lên CQT ngay sau đó.
        invoice = Invoice.with_context(meinvoice_skip_draft_mail=True).create({
            'pos_order_id': self.id,
            'inv_series': inv_series,
            'inv_date': inv_date,
            'payment_method': 'TM/CK',
            **buyer,
            'invoice_data_json': json.dumps(
                self._meinvoice_header_data(inv_series, inv_date), ensure_ascii=False,
            ),
            'line_ids': [(0, 0, vals) for vals in line_vals],
            'pos_auto_publish': bool(auto_publish),
            'pos_publish_error': hold_reason,
        })
        if mismatch:
            self._meinvoice_flag_review(hold_reason)
        _logger.info('meInvoice POS: tạo nháp id=%d cho %s', invoice.id, self.name)
        return invoice

    def _meinvoice_flag_review(self, reason):
        """Đánh dấu đơn cho kế toán xem; trả hóa đơn rỗng để gọi `return` gọn."""
        self.write({'meinvoice_review_needed': True, 'meinvoice_review_note': reason})
        _logger.info('meInvoice POS: %s cần kế toán xem: %s', self.name, reason)
        return self.env['meinvoice.invoice']

    def _meinvoice_line_inputs(self):
        """Quy dòng POS về dict số cho build_invoice_lines. ValueError nếu thuế không hỗ trợ."""
        currency = self.currency_id
        inputs = []
        for line in self.lines:
            # Dòng cha combo mang giá 0, tiền nằm ở các dòng con.
            if line.combo_line_ids and float_is_zero(
                line.price_subtotal_incl, precision_rounding=currency.rounding,
            ):
                continue
            if float_is_zero(line.qty, precision_digits=6):
                continue
            taxes = line.tax_ids_after_fiscal_position
            if len(taxes) > 1 or taxes.filtered(lambda t: t.amount_type != 'percent'):
                raise ValueError(
                    'Dòng "%s" có thuế không hỗ trợ (%s) — chỉ hỗ trợ một thuế phần trăm.'
                    % (line.full_product_name or line.product_id.display_name,
                       ', '.join(taxes.mapped('name')))
                )
            if taxes:
                gross_excl = taxes.compute_all(
                    line.price_unit, currency, line.qty,
                    product=line.product_id, partner=self.partner_id,
                )['total_excluded']
            else:
                gross_excl = currency.round(line.price_unit * line.qty)
            name = line.full_product_name or line.product_id.display_name or ''
            inputs.append({
                'name': re.sub(r'^\[.*?\]\s*', '', name),
                'code': line.product_id.default_code or '',
                'unit': line.product_uom_id.name or '',
                'qty': line.qty,
                'vat_rate': taxes.amount if taxes else 0.0,
                'gross_excl': gross_excl,
                'net_excl': line.price_subtotal,
                'vat': line.price_subtotal_incl - line.price_subtotal,
            })
        return inputs

    def _meinvoice_buyer_vals(self, config):
        """Thông tin người mua theo cấu hình: người tiêu dùng, hoặc khách có MST."""
        partner = self.partner_id
        company = partner.commercial_partner_id
        consumer_partners = config.meinvoice_pos_consumer_partner_ids
        use_partner = (
            config.meinvoice_pos_buyer_mode == 'partner_vat'
            and (company.vat or '').strip()
            and not (partner & consumer_partners or company & consumer_partners)
        )
        if not use_partner:
            return {
                'buyer_legal_name': '',
                'buyer_full_name': (config.meinvoice_pos_consumer_name or '').strip(),
                'buyer_tax_code': '',
                'buyer_address': '',
                'buyer_phone': '',
                'buyer_email': '',
            }
        return {
            'buyer_legal_name': company.name or '',
            'buyer_full_name': partner.name if partner != company else '',
            'buyer_tax_code': company.vat.strip(),
            'buyer_address': company.contact_address_complete or '',
            'buyer_phone': partner.phone or partner.mobile or company.phone or '',
            'buyer_email': partner.email or company.email or '',
        }

    def _meinvoice_header_data(self, inv_series, inv_date):
        """Phần đầu InvoiceData. Dòng, tổng tiền và người mua do meinvoice.invoice
        tự dựng lại từ line_ids / field người mua lúc tạo và lúc phát hành."""
        return {
            # Khác không gian tên RefID của đơn bán ('meinvoice|<id SO>'): id đơn
            # POS và id SO có thể trùng số nên phải tách, nếu không MISA báo trùng.
            'RefID': str(uuid.uuid5(uuid.NAMESPACE_DNS, 'meinvoice-pos|%d' % self.id)),
            'InvSeries': inv_series,
            'InvDate': inv_date.strftime('%Y-%m-%d'),
            'CurrencyCode': self.currency_id.name or 'VND',
            'ExchangeRate': 1.0,
            'PaymentMethodName': 'TM/CK',
            'IsInvoiceSummary': False,
            **seller_fields(self.company_id),
        }

    # ── Nút cho kế toán ─────────────────────────────────────────────────────

    def action_create_meinvoice_draft(self):
        """Tạo tay nháp HĐĐT (đơn trước khi bật tính năng, hoặc nháp cũ đã hủy)."""
        self._meinvoice_check_accountant()
        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        if not config.meinvoice_enabled:
            raise UserError('Tính năng phát hành HĐĐT meInvoice chưa được bật trong cấu hình.')
        created = self.env['meinvoice.invoice']
        for order in self:
            created |= order.sudo()._meinvoice_create_draft(config)
        if created.filtered('pos_auto_publish'):
            self.env.ref('amis_callback_pos.ir_cron_meinvoice_pos_publish').sudo()._trigger()
        if not created:
            # Không raise: raise sẽ rollback luôn đánh dấu "cần xem" vừa ghi.
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Không tạo hóa đơn',
                    'message': 'Đơn đã có hóa đơn hoặc cần kế toán xử lý tay — xem cột "Lý do cần xem".',
                    'type': 'warning',
                    'next': {'type': 'ir.actions.client', 'tag': 'reload'},
                },
            }
        return self._meinvoice_open_invoices(created)

    def action_meinvoice_review_done(self):
        # Kế toán chỉ có quyền đọc pos.order (cấp riêng trong module này).
        self._meinvoice_check_accountant()
        self.sudo().write({'meinvoice_review_needed': False})
        return True

    def _meinvoice_check_accountant(self):
        if not self.env.user.has_group('amis_callback.group_meinvoice_accountant'):
            raise UserError('Chỉ nhóm Kế toán HĐĐT được thao tác hóa đơn điện tử của đơn POS.')

    def action_view_meinvoice_invoices(self):
        return self._meinvoice_open_invoices(self.meinvoice_invoice_ids)

    def _meinvoice_open_invoices(self, invoices):
        if not invoices:
            raise UserError('Đơn này chưa có hóa đơn điện tử.')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Hóa đơn điện tử',
            'res_model': 'meinvoice.invoice',
            'view_mode': 'list,form',
            'domain': [('id', 'in', invoices.ids)],
            'target': 'current',
        }
