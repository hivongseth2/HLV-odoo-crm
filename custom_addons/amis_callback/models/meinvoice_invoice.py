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
            ('published', 'Đã phát hành'),
            ('cancelled', 'Đã hủy'),
        ],
        string='Trạng thái', default='draft', required=True,
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

        self.write({
            'state': 'published',
            'transaction_id': transaction_id,
            'inv_no': inv_no,
            'inv_code': inv_code,
            'inv_series_result': inv_series_result or new_series,
            'inv_date_result': inv_date_result or (
                inv_date.strftime('%Y-%m-%d') if inv_date else False
            ),
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
            'meInvoice published for SO %s: TransactionID=%s InvNo=%s',
            order.name, transaction_id, inv_no,
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Phát hành HĐĐT thành công',
                'message': 'Hóa đơn %s %s đã được phát hành. TransactionID: %s' % (
                    inv_series_result or new_series, inv_no, transaction_id,
                ),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_view_invoice(self):
        """Mở link xem hóa đơn đã phát hành trên cổng meInvoice (link tồn tại 5 phút)."""
        self.ensure_one()
        if self.state != 'published' or not self.transaction_id:
            raise UserError('Chỉ hóa đơn đã phát hành mới có thể xem.')
        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        view_url = config.get_meinvoice_publishview_url([self.transaction_id])
        if not view_url:
            raise UserError('meInvoice không trả về link xem hóa đơn.')
        return {'type': 'ir.actions.act_url', 'url': view_url, 'target': 'new'}

    def action_cancel(self):
        for rec in self:
            if rec.state == 'published':
                raise UserError('Không thể hủy hóa đơn đã phát hành.')
            rec.write({'state': 'cancelled'})
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
