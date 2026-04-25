# -*- coding: utf-8 -*-
import json
import base64
import logging
from datetime import datetime
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    # ─── MEinvoice fields ──────────────────────────────────────────────────────
    meinvoice_state = fields.Selection([
        ('not_sent',   'Chưa phát hành'),
        ('published',  'Đã phát hành'),
        ('cancelled',  'Đã hủy'),
        ('adjusted',   'Đã điều chỉnh'),
    ], string='Trạng thái MEinvoice',
       default='not_sent',
       copy=False,
       tracking=True,
    )
    meinvoice_transaction_id = fields.Char(
        'Transaction ID (MEinvoice)',
        copy=False,
        readonly=True,
        index=True,
    )
    meinvoice_inv_no = fields.Char(
        'Số hóa đơn điện tử',
        copy=False,
        readonly=True,
    )
    meinvoice_inv_series = fields.Char(
        'Ký hiệu hóa đơn',
        copy=False,
    )
    meinvoice_published_date = fields.Datetime(
        'Ngày phát hành điện tử',
        copy=False,
        readonly=True,
    )
    meinvoice_log_ids = fields.One2many(
        'meinvoice.log',
        'move_id',
        string='Lịch sử MEinvoice',
        readonly=True,
    )
    meinvoice_log_count = fields.Integer(
        compute='_compute_meinvoice_log_count',
        string='Số log',
    )
    meinvoice_pdf_attachment_id = fields.Many2one(
        'ir.attachment',
        string='PDF hóa đơn điện tử',
        copy=False,
        readonly=True,
    )
    meinvoice_xml_attachment_id = fields.Many2one(
        'ir.attachment',
        string='XML hóa đơn điện tử',
        copy=False,
        readonly=True,
    )

    # ─── Compute ───────────────────────────────────────────────────────────────

    @api.depends('meinvoice_log_ids')
    def _compute_meinvoice_log_count(self):
        for rec in self:
            rec.meinvoice_log_count = len(rec.meinvoice_log_ids)

    # ─── Auto publish on confirm ───────────────────────────────────────────────

    def action_post(self):
        res = super().action_post()
        auto = self.env['ir.config_parameter'].sudo().get_param(
            'meinvoice.auto_publish', 'False'
        )
        if auto == 'True':
            for move in self.filtered(
                lambda m: m.move_type in ('out_invoice', 'out_refund')
                and m.meinvoice_state == 'not_sent'
            ):
                try:
                    move.action_meinvoice_publish()
                except Exception as e:
                    _logger.warning(
                        'Auto-publish MEinvoice failed for move %s: %s',
                        move.name, e
                    )
        return res

    # ─── Build payload ─────────────────────────────────────────────────────────

    def _meinvoice_build_invoice_data(self):
        """Chuyển đổi account.move → dict theo chuẩn MEinvoice API."""
        self.ensure_one()
        params = self.env['ir.config_parameter'].sudo()
        inv_series = (
            self.meinvoice_inv_series
            or params.get_param('meinvoice.inv_series', '')
        )
        invoice_name = params.get_param(
            'meinvoice.invoice_name', 'Hóa đơn giá trị gia tăng'
        )

        partner = self.partner_id
        lines = []
        line_no = 1
        for line in self.invoice_line_ids.filtered(
            lambda l: l.display_type not in ('line_section', 'line_note')
        ):
            tax_rate = 0.0
            vat_rate_name = 'KCT'
            if line.tax_ids:
                t = line.tax_ids[0]
                tax_rate = abs(t.amount)
                vat_rate_name = (
                    f'{int(tax_rate)}%' if tax_rate else 'KCT'
                )

            price_unit = line.price_unit
            qty = line.quantity
            discount = line.discount or 0.0
            amount_oc = price_unit * qty * (1 - discount / 100)
            vat_amount = amount_oc * tax_rate / 100

            lines.append({
                'ItemType':           1,
                'LineNumber':         line_no,
                'ItemCode':           line.product_id.default_code or '',
                'ItemName':           line.name or line.product_id.name or '',
                'UnitName':           line.product_uom_id.name if line.product_uom_id else 'Cái',
                'Quantity':           qty,
                'UnitPrice':          price_unit,
                'DiscountRate':       discount,
                'DiscountAmountOC':   price_unit * qty * discount / 100,
                'AmountOC':           amount_oc,
                'Amount':             amount_oc,
                'AmountWithoutVATOC': amount_oc,
                'AmountWithoutVAT':   amount_oc,
                'VATRateName':        vat_rate_name,
                'VATAmountOC':        vat_amount,
                'VATAmount':          vat_amount,
            })
            line_no += 1

        total_without_vat = self.amount_untaxed
        total_vat = self.amount_tax
        total_amount = self.amount_total

        payload = {
            'RefID':                   str(self.id),
            'InvSeries':               inv_series,
            'InvoiceName':             invoice_name,
            'InvDate':                 self.invoice_date.isoformat() if self.invoice_date else datetime.today().date().isoformat(),
            'CurrencyCode':            self.currency_id.name or 'VND',
            'ExchangeRate':            self.currency_id.rate if self.currency_id.name != 'VND' else 1.0,
            'PaymentMethodName':       self._meinvoice_payment_method(),
            'BuyerLegalName':          partner.name or '',
            'BuyerTaxCode':            partner.vat or '',
            'BuyerAddress':            self._meinvoice_partner_address(partner),
            'BuyerCode':               str(partner.id),
            'BuyerPhoneNumber':        partner.phone or partner.mobile or '',
            'BuyerEmail':              partner.email or '',
            'BuyerFullName':           partner.name or '',
            'TotalSaleAmountOC':       total_without_vat,
            'TotalAmountWithoutVATOC': total_without_vat,
            'TotalVATAmountOC':        total_vat,
            'TotalAmountOC':           total_amount,
            'TotalSaleAmount':         total_without_vat,
            'TotalAmountWithoutVAT':   total_without_vat,
            'TotalVATAmount':          total_vat,
            'TotalAmount':             total_amount,
            'TotalAmountInWords':      self._meinvoice_amount_in_words(total_amount),
            'OriginalInvoiceDetail':   lines,
        }
        return payload

    def _meinvoice_payment_method(self):
        """Chuyển payment term sang tên phương thức thanh toán MEinvoice."""
        if self.invoice_payment_term_id:
            name = self.invoice_payment_term_id.name.lower()
            if 'tiền mặt' in name or 'cash' in name:
                return 'TM'
            if 'chuyển khoản' in name or 'transfer' in name or 'bank' in name:
                return 'CK'
        return 'TM/CK'

    def _meinvoice_partner_address(self, partner):
        parts = filter(None, [
            partner.street,
            partner.street2,
            partner.city,
            partner.state_id.name if partner.state_id else '',
            partner.country_id.name if partner.country_id else '',
        ])
        return ', '.join(parts)

    def _meinvoice_amount_in_words(self, amount):
        """Trả về số tiền bằng chữ đơn giản (placeholder)."""
        # Odoo có hàm currency_id.amount_to_text nhưng không phải lúc nào cũng có tiếng Việt
        # Có thể tích hợp thư viện num2words nếu cần
        return f'{amount:,.0f} đồng'

    # ─── Actions ───────────────────────────────────────────────────────────────

    def action_meinvoice_publish(self):
        """Phát hành hóa đơn điện tử lên MEinvoice."""
        for move in self:
            if move.move_type not in ('out_invoice', 'out_refund'):
                raise UserError(_('Chỉ phát hành hóa đơn bán hàng / giảm giá.'))
            if move.state != 'posted':
                raise UserError(_('Hóa đơn phải ở trạng thái Đã xác nhận.'))
            if move.meinvoice_state == 'published':
                raise UserError(_('Hóa đơn này đã được phát hành trên MEinvoice.'))

            payload = move._meinvoice_build_invoice_data()
            try:
                result = self.env['meinvoice.api'].api_publish_invoice(payload)
                transaction_id = (
                    result if isinstance(result, str)
                    else (result or {}).get('TransactionID', '')
                )
                move.write({
                    'meinvoice_state':          'published',
                    'meinvoice_transaction_id': transaction_id,
                    'meinvoice_published_date': fields.Datetime.now(),
                })
                move._meinvoice_log('publish', 'success', transaction_id,
                                    'Phát hành thành công', payload, result)
                _logger.info('MEinvoice published: move=%s txn=%s', move.name, transaction_id)
            except Exception as e:
                move._meinvoice_log('publish', 'error', '', str(e), payload, {})
                raise

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title':   _('MEinvoice'),
                'message': _('Phát hành hóa đơn thành công!'),
                'type':    'success',
                'sticky': False,
            },
        }

    def action_meinvoice_cancel(self):
        """Mở wizard hủy hóa đơn."""
        self.ensure_one()
        if self.meinvoice_state != 'published':
            raise UserError(_('Chỉ hủy được hóa đơn đã phát hành.'))
        return {
            'name':   _('Hủy hóa đơn điện tử'),
            'type':   'ir.actions.act_window',
            'res_model': 'meinvoice.cancel.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_move_id': self.id},
        }

    def action_meinvoice_adjust(self):
        """Mở wizard điều chỉnh hóa đơn."""
        self.ensure_one()
        if self.meinvoice_state != 'published':
            raise UserError(_('Chỉ điều chỉnh được hóa đơn đã phát hành.'))
        return {
            'name':   _('Điều chỉnh hóa đơn điện tử'),
            'type':   'ir.actions.act_window',
            'res_model': 'meinvoice.adjust.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_move_id': self.id},
        }

    def action_meinvoice_search(self):
        """Tra cứu trạng thái hóa đơn từ MEinvoice."""
        self.ensure_one()
        if not self.meinvoice_transaction_id:
            raise UserError(_('Hóa đơn chưa có Transaction ID MEinvoice.'))
        try:
            data = self.env['meinvoice.api'].api_search_invoice(
                transaction_id=self.meinvoice_transaction_id
            )
            self._meinvoice_log('search', 'success', self.meinvoice_transaction_id,
                                json.dumps(data, ensure_ascii=False)[:500], {}, data)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title':   _('Tra cứu MEinvoice'),
                    'message': _('Dữ liệu hóa đơn: %s') % json.dumps(data, ensure_ascii=False)[:200],
                    'type':    'info',
                    'sticky': True,
                },
            }
        except Exception as e:
            self._meinvoice_log('search', 'error', self.meinvoice_transaction_id, str(e), {}, {})
            raise

    def action_meinvoice_download_pdf(self):
        """Tải PDF hóa đơn và lưu vào ir.attachment."""
        return self._meinvoice_download_file('Pdf')

    def action_meinvoice_download_xml(self):
        """Tải XML hóa đơn và lưu vào ir.attachment."""
        return self._meinvoice_download_file('Xml')

    def _meinvoice_download_file(self, file_type):
        self.ensure_one()
        if not self.meinvoice_transaction_id:
            raise UserError(_('Hóa đơn chưa có Transaction ID MEinvoice.'))

        data = self.env['meinvoice.api'].api_download_invoice(
            [self.meinvoice_transaction_id], file_type
        )

        if not data:
            raise UserError(_('Không nhận được dữ liệu từ MEinvoice.'))

        file_item = data[0] if isinstance(data, list) else data
        raw = file_item.get('Data', '')

        if file_type == 'Xml':
            content = raw.encode('utf-8') if isinstance(raw, str) else raw
            b64 = base64.b64encode(content).decode()
            fname = f'hoadon_{self.meinvoice_transaction_id}.xml'
            mimetype = 'application/xml'
            field = 'meinvoice_xml_attachment_id'
        else:
            # PDF trả về base64 string
            b64 = raw if isinstance(raw, str) else base64.b64encode(raw).decode()
            fname = f'hoadon_{self.meinvoice_transaction_id}.pdf'
            mimetype = 'application/pdf'
            field = 'meinvoice_pdf_attachment_id'

        attachment = self.env['ir.attachment'].create({
            'name':     fname,
            'type':     'binary',
            'datas':    b64,
            'res_model': self._name,
            'res_id':   self.id,
            'mimetype': mimetype,
        })
        self.write({field: attachment.id})
        self._meinvoice_log('download', 'success', self.meinvoice_transaction_id,
                            f'Đã tải {file_type}', {}, {})
        return {
            'type': 'ir.actions.act_url',
            'url':  f'/web/content/{attachment.id}?download=true',
            'target': 'new',
        }

    def action_meinvoice_view_logs(self):
        self.ensure_one()
        return {
            'name':   _('Lịch sử MEinvoice'),
            'type':   'ir.actions.act_window',
            'res_model': 'meinvoice.log',
            'view_mode': 'list,form',
            'domain': [('move_id', '=', self.id)],
            'context': {'default_move_id': self.id},
        }

    # ─── Log helper ────────────────────────────────────────────────────────────

    def _meinvoice_log(self, action, state, transaction_id, message,
                       request_data, response_data):
        self.env['meinvoice.log'].sudo().create({
            'move_id':        self.id,
            'action':         action,
            'state':          state,
            'transaction_id': transaction_id,
            'message':        message,
            'request_data':   json.dumps(request_data, ensure_ascii=False, default=str) if request_data else '',
            'response_data':  json.dumps(response_data, ensure_ascii=False, default=str) if response_data else '',
        })
