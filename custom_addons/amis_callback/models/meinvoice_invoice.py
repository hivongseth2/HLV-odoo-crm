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
    _inherit = ['mail.thread', 'mail.activity.mixin']
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

    # ── Trạng thái gửi email ────────────────────────────────────────────────
    mail_sent = fields.Boolean(string='Đã gửi email', default=False, copy=False)
    mail_last_sent_at = fields.Datetime(string='Lần gửi email cuối', readonly=True, copy=False)
    mail_last_sent_to = fields.Char(string='Email đã gửi đến', readonly=True, copy=False)
    mail_sent_count = fields.Integer(string='Số lần đã gửi', default=0, readonly=True, copy=False)

    # ─────────────────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        try:
            config = self.env['amis.callback.config'].sudo().search([], limit=1)
            if (config and config.meinvoice_mail_enabled
                    and config.meinvoice_mail_auto_send_draft):
                for rec in records:
                    if rec.state == 'draft' and (rec.buyer_email or '').strip():
                        rec.with_context(meinvoice_auto_mail=True)._send_meinvoice_mail(
                            mode='draft', raise_on_error=False,
                        )
        except Exception:
            _logger.exception('meInvoice: auto-send draft email thất bại (bỏ qua).')
        return records

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

        self.write({
            'state': 'submitted',
            'transaction_id': transaction_id,
            'inv_no': inv_no,
            'inv_code': inv_code,
            'inv_series_result': inv_series_result or new_series,
            'inv_date_result': inv_date_result or (
                inv_date.strftime('%Y-%m-%d') if inv_date else False
            ),
            'cqt_check_queued': True,  # đưa vào queue cron check CQT
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
            'meInvoice submitted for SO %s: TransactionID=%s InvNo=%s — chờ CQT xác nhận.',
            order.name, transaction_id, inv_no,
        )

        # Auto-send email cho khách hàng (mẫu "Đã cấp mã") nếu được cấu hình
        try:
            if (config.meinvoice_mail_enabled
                    and config.meinvoice_mail_auto_send_published
                    and (self.buyer_email or '').strip()):
                self.with_context(meinvoice_auto_mail=True)._send_meinvoice_mail(
                    mode='published', raise_on_error=False,
                )
        except Exception:
            _logger.exception('meInvoice: auto-send published email thất bại (bỏ qua).')

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Đã gửi lên Cơ quan Thuế',
                'message': 'Hóa đơn %s %s đã được gửi. TransactionID: %s — Hệ thống sẽ tự kiểm tra kết quả CQT.' % (
                    inv_series_result or new_series, inv_no, transaction_id,
                ),
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
            self.write({'cqt_checked_at': now})
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Kiểm tra CQT',
                    'message': 'meInvoice không trả về trạng thái cho hóa đơn này.',
                    'type': 'warning', 'sticky': False,
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
        url = config.get_meinvoice_download_url(self.transaction_id, file_type='PDF')
        if not url:
            raise UserError('meInvoice không trả về link tải PDF.')
        return {'type': 'ir.actions.act_url', 'url': url, 'target': 'new'}

    def action_download_xml(self):
        """Tải hóa đơn dạng XML từ meInvoice."""
        self.ensure_one()
        if self.state not in ('submitted', 'accepted', 'rejected') or not self.transaction_id:
            raise UserError('Chỉ hóa đơn đã gửi CQT mới có thể tải xuống.')
        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        url = config.get_meinvoice_download_url(self.transaction_id, file_type='XML')
        if not url:
            raise UserError('meInvoice không trả về link tải XML.')
        return {'type': 'ir.actions.act_url', 'url': url, 'target': 'new'}

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

    # ── Gửi email cho khách hàng ────────────────────────────────────────────

    def _get_mail_mode(self):
        """Xác định mẫu email phù hợp theo trạng thái hóa đơn."""
        self.ensure_one()
        # Có số HĐ / mã CQT → coi như đã cấp mã
        if self.inv_no or self.state in ('submitted', 'accepted', 'rejected'):
            return 'published'
        return 'draft'

    def _get_mail_template(self, mode=None):
        """Lấy mail.template theo cấu hình; fallback theo XML id mặc định."""
        self.ensure_one()
        mode = mode or self._get_mail_mode()
        config = self.env['amis.callback.config'].sudo().search([], limit=1)
        template = False
        if config:
            if mode == 'draft':
                template = config.meinvoice_mail_template_draft_id
            else:
                template = config.meinvoice_mail_template_published_id
        if not template:
            xmlid = ('amis_callback.mail_template_meinvoice_draft' if mode == 'draft'
                     else 'amis_callback.mail_template_meinvoice_published')
            template = self.env.ref(xmlid, raise_if_not_found=False)
        return template

    def _meinvoice_pdf_attachment(self):
        """Tải PDF từ meInvoice và tạo ir.attachment đính kèm vào record."""
        self.ensure_one()
        if not self.transaction_id:
            return self.env['ir.attachment']
        config = self.env['amis.callback.config'].sudo().search([], limit=1)
        if not config or not config.meinvoice_mail_attach_pdf:
            return self.env['ir.attachment']
        try:
            pdf_bytes = config.get_meinvoice_pdf_bytes(self.transaction_id)
        except Exception:
            _logger.exception('meInvoice: lấy PDF thất bại cho TransactionID=%s', self.transaction_id)
            return self.env['ir.attachment']
        if not pdf_bytes:
            return self.env['ir.attachment']
        import base64
        fname = 'HoaDon_%s_%s.pdf' % (
            (self.inv_series_result or self.inv_series or 'meinvoice').replace('/', '-'),
            (self.inv_no or self.transaction_id or 'draft'),
        )
        return self.env['ir.attachment'].sudo().create({
            'name': fname,
            'datas': base64.b64encode(pdf_bytes),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })

    def _send_meinvoice_mail(self, mode=None, raise_on_error=True):
        """Gửi email cho khách hàng theo mẫu cấu hình.

        Args:
            mode: 'draft' hoặc 'published'. None → tự xác định theo trạng thái.
            raise_on_error: True → raise UserError khi thiếu cấu hình/email.
        """
        from datetime import datetime as _dt
        for rec in self:
            mode_ = mode or rec._get_mail_mode()
            email_to = (rec.buyer_email or '').strip()
            if not email_to:
                if raise_on_error:
                    raise UserError('Khách hàng chưa có email — không thể gửi.')
                _logger.info('meInvoice: bỏ qua gửi mail cho HĐ id=%s (không có email).', rec.id)
                continue
            template = rec._get_mail_template(mode_)
            if not template:
                if raise_on_error:
                    raise UserError(
                        'Chưa cấu hình mẫu email "%s" cho meInvoice. '
                        'Vào Cấu hình AMIS Callback để thiết lập.'
                        % ('Bản nháp' if mode_ == 'draft' else 'Đã cấp mã')
                    )
                continue

            config = self.env['amis.callback.config'].sudo().search([], limit=1)
            email_cc = (config.meinvoice_mail_cc or '').strip() if config else ''

            attachment_ids = []
            if mode_ == 'published':
                att = rec._meinvoice_pdf_attachment()
                if att:
                    attachment_ids = [att.id]

            ctx = dict(self.env.context)
            ctx['meinvoice_force_email_to'] = email_to
            ctx['meinvoice_force_email_cc'] = email_cc

            tpl = template.with_context(ctx)
            try:
                values = tpl.generate_email(
                    rec.id, ['subject', 'body_html', 'email_from', 'reply_to']
                )
                values.setdefault('email_from', tpl.email_from or self.env.user.email or '')
                values['email_to'] = email_to
                if email_cc:
                    values['email_cc'] = email_cc
                values['model'] = rec._name
                values['res_id'] = rec.id
                values['auto_delete'] = False
                if attachment_ids:
                    values['attachment_ids'] = [(6, 0, attachment_ids)]
                mail = self.env['mail.mail'].sudo().create(values)
                mail.send(raise_exception=False)
                sent_ok = mail.state == 'sent'
            except Exception:
                _logger.exception('meInvoice: gửi mail HĐ id=%s thất bại.', rec.id)
                if raise_on_error:
                    raise
                sent_ok = False

            rec.sudo().write({
                'mail_sent': rec.mail_sent or sent_ok,
                'mail_last_sent_at': _dt.utcnow(),
                'mail_last_sent_to': email_to,
                'mail_sent_count': (rec.mail_sent_count or 0) + (1 if sent_ok else 0),
            })

            # Ghi nhận vào chatter
            try:
                if sent_ok:
                    rec.message_post(
                        body='Đã gửi email HĐĐT (%s) tới <b>%s</b>%s.' % (
                            'bản nháp' if mode_ == 'draft' else 'đã cấp mã',
                            email_to,
                            (' — CC: ' + email_cc) if email_cc else '',
                        ),
                        subtype_xmlid='mail.mt_note',
                    )
                else:
                    rec.message_post(
                        body='Gửi email HĐĐT tới %s thất bại — xem log.' % email_to,
                        subtype_xmlid='mail.mt_note',
                    )
            except Exception:
                pass

        return True

    def action_send_mail(self):
        """Nút bấm: gửi email cho khách hàng (tự chọn mẫu theo trạng thái)."""
        self.ensure_one()
        config = self.env['amis.callback.config'].sudo().search([], limit=1)
        if not config or not config.meinvoice_mail_enabled:
            raise UserError(
                'Chức năng gửi email HĐĐT chưa được bật. '
                'Vào Cấu hình AMIS Callback → meInvoice để bật.'
            )
        self._send_meinvoice_mail(raise_on_error=True)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Đã gửi email',
                'message': 'Email HĐĐT đã được gửi tới %s.' % (self.buyer_email or ''),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_open_send_mail_wizard(self):
        """Mở composer mail chuẩn của Odoo (cho phép chỉnh sửa trước khi gửi)."""
        self.ensure_one()
        config = self.env['amis.callback.config'].sudo().search([], limit=1)
        if not config or not config.meinvoice_mail_enabled:
            raise UserError(
                'Chức năng gửi email HĐĐT chưa được bật. '
                'Vào Cấu hình AMIS Callback → meInvoice để bật.'
            )
        template = self._get_mail_template()
        compose_form = self.env.ref('mail.email_compose_message_wizard_form', raise_if_not_found=False)

        # Tải sẵn attachment PDF nếu đã cấp mã
        attachment_ids = []
        if self._get_mail_mode() == 'published':
            att = self._meinvoice_pdf_attachment()
            if att:
                attachment_ids = [att.id]

        ctx = {
            'default_model': self._name,
            'default_res_ids': [self.id],
            'default_use_template': bool(template),
            'default_template_id': template.id if template else False,
            'default_composition_mode': 'comment',
            'default_email_layout_xmlid': 'mail.mail_notification_light',
            'default_partner_ids': [],
            'default_email_to': (self.buyer_email or '').strip(),
            'default_email_cc': (config.meinvoice_mail_cc or '').strip(),
            'default_attachment_ids': [(6, 0, attachment_ids)] if attachment_ids else False,
            'force_email': True,
            'mark_meinvoice_mail_sent': True,
        }
        return {
            'name': 'Gửi email HĐĐT',
            'type': 'ir.actions.act_window',
            'res_model': 'mail.compose.message',
            'views': [(compose_form.id if compose_form else False, 'form')],
            'view_id': compose_form.id if compose_form else False,
            'target': 'new',
            'context': ctx,
        }


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
