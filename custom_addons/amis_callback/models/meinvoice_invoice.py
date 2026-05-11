# -*- coding: utf-8 -*-
import json
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MeinvoiceInvoice(models.Model):
    """Hóa đơn điện tử meInvoice — lưu trữ bền vững, hỗ trợ trạng thái nháp/đã phát hành."""

    _name = 'meinvoice.invoice'
    _description = 'Hóa đơn điện tử meInvoice'
    _rec_name = 'name'
    _order = 'create_date desc'

    name = fields.Char(
        string='Tiêu đề',
        compute='_compute_name',
        store=True,
    )

    @api.depends('sale_order_id', 'inv_no', 'inv_series')
    def _compute_name(self):
        for rec in self:
            if rec.inv_no:
                rec.name = '%s %s' % (rec.inv_series or '', rec.inv_no)
            elif rec.sale_order_id:
                rec.name = 'Nháp — %s' % rec.sale_order_id.name
            else:
                rec.name = 'Nháp #%d' % (rec.id or 0)

    sale_order_id = fields.Many2one(
        'sale.order', string='Đơn hàng', ondelete='restrict', required=True, readonly=True, index=True,
    )
    partner_id = fields.Many2one(
        related='sale_order_id.partner_id', string='Khách hàng', store=True, readonly=True,
    )
    state = fields.Selection(
        [
            ('draft', 'Nháp'),
            ('submitted', 'Đã gửi CQT'),
            ('accepted', 'CQT chấp nhận'),
            ('rejected', 'CQT từ chối'),
            ('cancelled', 'Đã hủy'),
        ],
        string='Trạng thái', default='draft', required=True, tracking=True,
    )

    # ── Thông tin hóa đơn (chỉnh sửa được khi nháp) ─────────────────────────
    inv_series = fields.Char(string='Ký hiệu HĐ', required=True)
    inv_date = fields.Date(string='Ngày HĐ', required=True)
    payment_method = fields.Char(string='Phương thức TT', default='TM/CK')

    # ── Thông tin người mua ───────────────────────────────────────────────────
    buyer_legal_name = fields.Char(string='Tên đơn vị (pháp lý)')
    buyer_full_name = fields.Char(string='Họ tên người mua')
    buyer_tax_code = fields.Char(string='MST người mua')
    buyer_address = fields.Char(string='Địa chỉ người mua')
    buyer_phone = fields.Char(string='SĐT người mua')
    buyer_email = fields.Char(string='Email người mua')

    # ── Tổng tiền (readonly, tính từ SO lúc tạo nháp) ────────────────────────
    currency_id = fields.Many2one(
        'res.currency', string='Tiền tệ', default=lambda self: self.env.ref('base.VND'),
        readonly=True,
    )
    total_sale_oc = fields.Float(
        string='Thành tiền (trước CK, trước thuế)', readonly=True, digits=(16, 0),
    )
    total_discount_oc = fields.Float(string='Tiền chiết khấu', readonly=True, digits=(16, 0))
    total_net_oc = fields.Float(string='Chưa có thuế', readonly=True, digits=(16, 0))
    total_vat_oc = fields.Float(string='Tiền thuế GTGT', readonly=True, digits=(16, 0))
    total_amount_oc = fields.Float(
        string='Tổng cộng tiền thanh toán', readonly=True, digits=(16, 0),
    )
    total_amount_in_words = fields.Char(string='Số tiền bằng chữ', readonly=True)

    # ── Dòng hàng hóa ────────────────────────────────────────────────────────
    line_ids = fields.One2many(
        'meinvoice.invoice.line', 'invoice_id', string='Chi tiết hàng hóa',
    )

    # ── Raw payload để rebuild khi publish ───────────────────────────────────
    invoice_data_json = fields.Text(string='Invoice Data JSON (raw)')

    # ── Kết quả sau khi phát hành (readonly) ─────────────────────────────────
    transaction_id = fields.Char(string='Transaction ID', readonly=True, copy=False)
    inv_no = fields.Char(string='Số hóa đơn', readonly=True, copy=False)
    inv_code = fields.Char(string='Mã CQT', readonly=True, copy=False)
    inv_series_result = fields.Char(string='Ký hiệu (kết quả)', readonly=True, copy=False)
    inv_date_result = fields.Date(string='Ngày HĐ (kết quả)', readonly=True, copy=False)

    # ── Trạng thái CQT chi tiết (từ API /invoice/status) ────────────────────
    cqt_status_code = fields.Char(string='Mã trạng thái CQT (raw)', readonly=True, copy=False)
    cqt_status_desc = fields.Char(string='Mô tả trạng thái CQT', readonly=True, copy=False)
    cqt_checked_at = fields.Datetime(string='Kiểm tra CQT lúc', readonly=True, copy=False)
    cqt_check_queued = fields.Boolean(
        string='Cần kiểm tra CQT', default=False, copy=False, index=True,
        help='Cron sẽ gọi /invoice/status để cập nhật trạng thái khi field này là True.',
    )

    # ─────────────────────────────────────────────────────────────────────────

    def action_publish(self):
        """Gửi hóa đơn lên Cơ quan Thuế qua meInvoice API."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError('Chỉ hóa đơn ở trạng thái Nháp mới có thể phát hành.')

        try:
            invoice_data = json.loads(self.invoice_data_json or '{}')
        except Exception:
            raise UserError('Dữ liệu hóa đơn bị hỏng. Vui lòng xóa và tạo lại từ đơn hàng.')

        # Patch buyer fields và thông tin hóa đơn từ các trường hiện tại
        inv_date = self.inv_date
        new_series = (self.inv_series or '').strip()
        invoice_data['InvSeries'] = new_series
        invoice_data['InvDate'] = (
            inv_date.strftime('%Y-%m-%d') if inv_date else invoice_data.get('InvDate', '')
        )
        invoice_data['PaymentMethodName'] = (self.payment_method or 'TM/CK').strip()
        invoice_data['BuyerLegalName'] = (self.buyer_legal_name or '').strip()
        invoice_data['BuyerFullName'] = (self.buyer_full_name or '').strip()
        invoice_data['BuyerTaxCode'] = (self.buyer_tax_code or '').strip()
        invoice_data['BuyerAddress'] = (self.buyer_address or '').strip()
        invoice_data['BuyerPhoneNumber'] = (self.buyer_phone or '').strip()
        invoice_data['BuyerEmail'] = (self.buyer_email or '').strip()
        invoice_data['IsInvoiceCalculatingMachine'] = (
            len(new_series) >= 5 and new_series[4].upper() == 'M'
        )

        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        results = config.push_meinvoice_invoice([invoice_data])

        transaction_id = ''
        inv_no = ''
        inv_code = ''
        inv_series_result = ''
        inv_date_result = False
        if results and isinstance(results, list):
            first = results[0] if results else {}
            transaction_id = str(first.get('TransactionID') or '')
            inv_no = str(first.get('InvNo') or '')
            inv_code = str(first.get('InvCode') or '')
            inv_series_result = str(first.get('InvSeries') or '')
            raw_date = first.get('InvDate') or ''
            if raw_date:
                try:
                    inv_date_result = str(raw_date)[:10]
                except Exception:
                    pass
            err_code = first.get('ErrorCode') or ''
            if err_code:
                raise UserError('meInvoice phát hành lỗi: %s' % err_code)

        # Nếu InvCode trả về ngay → CQT đã cấp mã, không cần chờ
        new_state = 'accepted' if inv_code else 'submitted'
        self.write({
            'state': new_state,
            'transaction_id': transaction_id,
            'inv_no': inv_no,
            'inv_code': inv_code,
            'inv_series_result': inv_series_result or new_series,
            'inv_date_result': inv_date_result or (
                inv_date.strftime('%Y-%m-%d') if inv_date else False
            ),
            'cqt_check_queued': new_state == 'submitted',  # chỉ queue nếu chưa có InvCode
        })

        # Cập nhật SO để backward compat với các field kết quả trên đơn hàng
        order = self.sale_order_id
        order.sudo().write({
            'misa_meinvoice_synced': True,
            'misa_meinvoice_transaction_id': transaction_id,
            'misa_meinvoice_inv_no': inv_no,
            'misa_meinvoice_inv_code': inv_code,
            'misa_meinvoice_inv_series': inv_series_result or new_series,
            'misa_meinvoice_inv_date': inv_date_result or (
                inv_date.strftime('%Y-%m-%d') if inv_date else False
            ),
        })

        _logger.info(
            'meInvoice submitted for SO %s: TransactionID=%s InvNo=%s InvCode=%s state=%s',
            order.name, transaction_id, inv_no, inv_code, new_state,
        )

        if new_state == 'accepted':
            msg = 'Hóa đơn %s %s đã được Cơ quan Thuế cấp mã: %s' % (
                inv_series_result or new_series, inv_no, inv_code,
            )
        else:
            msg = 'Hóa đơn %s %s đã được gửi. TransactionID: %s — Hệ thống sẽ tự kiểm tra kết quả CQT.' % (
                inv_series_result or new_series, inv_no, transaction_id,
            )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Đã gửi lên Cơ quan Thuế',
                'message': msg,
                'type': 'success',
                'sticky': False,
            },
        }

    def action_preview_invoice(self):
        """Xem trước hóa đơn nháp trên meInvoice (chưa phát hành, link tồn tại 5 phút)."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError('Chỉ hóa đơn ở trạng thái Nháp mới có thể xem trước.')
        if not self.invoice_data_json:
            raise UserError('Chưa có dữ liệu hóa đơn. Vui lòng xóa và tạo lại từ đơn hàng.')

        try:
            invoice_data = json.loads(self.invoice_data_json)
        except Exception:
            raise UserError('Dữ liệu hóa đơn bị hỏng. Vui lòng xóa và tạo lại từ đơn hàng.')

        # Patch buyer fields từ các trường hiện tại (giống action_publish)
        inv_date = self.inv_date
        new_series = (self.inv_series or '').strip()
        invoice_data['InvSeries'] = new_series
        invoice_data['InvDate'] = (
            inv_date.strftime('%Y-%m-%d') if inv_date else invoice_data.get('InvDate', '')
        )
        invoice_data['PaymentMethodName'] = (self.payment_method or 'TM/CK').strip()
        invoice_data['BuyerLegalName'] = (self.buyer_legal_name or '').strip()
        invoice_data['BuyerFullName'] = (self.buyer_full_name or '').strip()
        invoice_data['BuyerTaxCode'] = (self.buyer_tax_code or '').strip()
        invoice_data['BuyerAddress'] = (self.buyer_address or '').strip()
        invoice_data['BuyerPhoneNumber'] = (self.buyer_phone or '').strip()
        invoice_data['BuyerEmail'] = (self.buyer_email or '').strip()
        invoice_data['IsInvoiceCalculatingMachine'] = (
            len(new_series) >= 5 and new_series[4].upper() == 'M'
        )

        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        result = config._post_meinvoice('/invoice/unpublishview', payload=invoice_data)
        view_url = result.get('data') or result.get('Data') or ''
        if not view_url:
            err = result.get('errorCode') or result.get('ErrorCode') or ''
            raise UserError('meInvoice không trả về link xem trước.%s' % (' Lỗi: ' + err if err else ''))

        _logger.info('meInvoice unpublishview URL: %s', view_url)
        return {'type': 'ir.actions.act_url', 'url': view_url, 'target': 'new'}

    def action_check_cqt_status(self):
        """Kiểm tra trạng thái CQT của hóa đơn đã gửi CQT."""
        self.ensure_one()
        if self.state not in ('submitted', 'accepted', 'rejected') or not self.transaction_id:
            raise UserError('Chỉ hóa đơn đã gửi CQT mới có thể kiểm tra trạng thái.')
        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        status_list = config.get_meinvoice_invoice_status([self.transaction_id])

        from datetime import datetime as _dt
        now = _dt.utcnow()
        if not status_list:
            # Nếu InvCode đã có → CQT đã cấp mã trước đó (từ POST /invoice response)
            if self.inv_code:
                self.write({'state': 'accepted', 'cqt_check_queued': False, 'cqt_checked_at': now})
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Kiểm tra CQT',
                        'message': 'Hóa đơn đã được Cơ quan Thuế cấp mã: %s' % self.inv_code,
                        'type': 'success', 'sticky': False,
                    },
                }
            self.write({'cqt_checked_at': now})
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Kiểm tra CQT',
                    'message': 'Hóa đơn đã được cấp số trên meInvoice và đang chờ chuyển tiếp lên Cơ quan Thuế. Vui lòng kiểm tra lại sau.',
                    'type': 'info', 'sticky': False,
                },
            }

        item = status_list[0]
        if not isinstance(item, dict):
            _logger.warning('meInvoice /invoice/status trả về item không phải dict: %r', item)
            self.write({'cqt_checked_at': now})
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Kiểm tra CQT',
                    'message': 'meInvoice trả về định dạng không xác định: %s' % str(item)[:200],
                    'type': 'warning', 'sticky': True,
                },
            }
        raw_status = item.get('InvStatus') or item.get('invStatus') or item.get('Status') or 0
        desc = (item.get('Description') or item.get('description') or '').strip()
        try:
            raw_status = int(raw_status)
        except (TypeError, ValueError):
            raw_status = 0

        if raw_status == 2:
            new_state = 'accepted'
            msg_type = 'success'
            msg = 'Cơ quan Thuế đã chấp nhận hóa đơn.'
        elif raw_status == 3:
            new_state = 'rejected'
            msg_type = 'danger'
            msg = 'Cơ quan Thuế từ chối hóa đơn.'
        elif raw_status == 1:
            new_state = 'submitted'
            msg_type = 'info'
            msg = 'Đang chờ Cơ quan Thuế xác nhận.'
        else:
            new_state = self.state
            msg_type = 'warning'
            msg = 'Không xác định được trạng thái CQT (mã: %s).' % raw_status

        self.write({
            'state': new_state,
            'cqt_status_code': str(raw_status),
            'cqt_status_desc': desc or msg,
            'cqt_checked_at': now,
            'cqt_check_queued': new_state == 'submitted',  # re-queue nếu vẫn đang chờ
        })
        _logger.info('CQT status check %s → %s: %s', self.transaction_id, new_state, desc)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Trạng thái CQT',
                'message': '%s%s' % (msg, (' — ' + desc) if desc and desc != msg else ''),
                'type': msg_type, 'sticky': False,
            },
        }

    def action_download_pdf(self):
        """Tải hóa đơn dạng PDF từ meInvoice."""
        self.ensure_one()
        if self.state not in ('submitted', 'accepted', 'rejected') or not self.transaction_id:
            raise UserError('Chỉ hóa đơn đã gửi CQT mới có thể tải xuống.')
        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        b64_data = config.get_meinvoice_download_url(self.transaction_id, file_type='PDF')
        filename = 'HoaDon_%s_%s.pdf' % (self.inv_series_result or '', self.inv_no or str(self.id))
        attachment = self.env['ir.attachment'].sudo().create({
            'name': filename,
            'type': 'binary',
            'datas': b64_data,
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%d?download=true' % attachment.id,
            'target': 'new',
        }

    def action_download_xml(self):
        """Tải hóa đơn dạng XML từ meInvoice."""
        self.ensure_one()
        if self.state not in ('submitted', 'accepted', 'rejected') or not self.transaction_id:
            raise UserError('Chỉ hóa đơn đã gửi CQT mới có thể tải xuống.')
        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        b64_data = config.get_meinvoice_download_url(self.transaction_id, file_type='XML')
        filename = 'HoaDon_%s_%s.xml' % (self.inv_series_result or '', self.inv_no or str(self.id))
        attachment = self.env['ir.attachment'].sudo().create({
            'name': filename,
            'type': 'binary',
            'datas': b64_data,
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/xml',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%d?download=true' % attachment.id,
            'target': 'new',
        }

    def action_view_invoice(self):
        """Mở link xem hóa đơn đã gửi CQT trên cổng meInvoice (link tồn tại 5 phút)."""
        self.ensure_one()
        if self.state not in ('submitted', 'accepted', 'rejected') or not self.transaction_id:
            raise UserError('Chỉ hóa đơn đã gửi CQT mới có thể xem.')
        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        view_url = config.get_meinvoice_publishview_url([self.transaction_id])
        if not view_url:
            raise UserError('meInvoice không trả về link xem hóa đơn.')
        return {'type': 'ir.actions.act_url', 'url': view_url, 'target': 'new'}

    def action_cancel(self):
        for rec in self:
            if rec.state in ('accepted',):
                raise UserError('Không thể hủy hóa đơn đã được CQT chấp nhận.')
            rec.write({'state': 'cancelled', 'cqt_check_queued': False})
        return True


class MeinvoiceInvoiceLine(models.Model):
    _name = 'meinvoice.invoice.line'
    _description = 'Dòng hàng hóa hóa đơn meInvoice'
    _order = 'sort_order'

    invoice_id = fields.Many2one('meinvoice.invoice', ondelete='cascade', required=True)
    sort_order = fields.Integer(string='STT')
    item_code = fields.Char(string='Mã hàng')
    item_name = fields.Char(string='Tên hàng hóa/dịch vụ')
    unit_name = fields.Char(string='ĐVT')
    quantity = fields.Float(string='Số lượng', digits=(16, 3))
    unit_price = fields.Float(string='Đơn giá', digits=(16, 2))
    discount_rate = fields.Float(string='% CK', digits=(16, 2))
    discount_amount_oc = fields.Float(string='Tiền CK', digits=(16, 0))
    amount_oc = fields.Float(string='Thành tiền', digits=(16, 0))
    amount_without_vat_oc = fields.Float(string='Tiền trước thuế', digits=(16, 0))
    vat_rate_name = fields.Char(string='Thuế suất')
    vat_amount_oc = fields.Float(string='Tiền thuế', digits=(16, 0))
