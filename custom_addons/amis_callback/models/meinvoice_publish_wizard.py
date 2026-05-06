# -*- coding: utf-8 -*-
import json
import logging

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MeinvoicePublishWizard(models.TransientModel):
    """Wizard xem trước và xác nhận phát hành hóa đơn điện tử meInvoice."""

    _name = 'meinvoice.publish.wizard'
    _description = 'Xem trước hóa đơn điện tử trước khi gửi CQT'

    sale_order_id = fields.Many2one('sale.order', required=True, ondelete='cascade')

    # ── Thông tin hóa đơn có thể chỉnh sửa ────────────────────────────────────
    inv_series = fields.Char(string='Ký hiệu HĐ', required=True)
    inv_date = fields.Date(string='Ngày HĐ', required=True)
    payment_method = fields.Char(string='Phương thức TT', default='TM/CK')

    buyer_legal_name = fields.Char(string='Tên người mua (pháp lý)')
    buyer_full_name = fields.Char(string='Họ tên người mua')
    buyer_tax_code = fields.Char(string='MST người mua')
    buyer_address = fields.Char(string='Địa chỉ người mua')
    buyer_phone = fields.Char(string='SĐT người mua')
    buyer_email = fields.Char(string='Email người mua')

    # ── Tổng tiền (chỉ đọc) ───────────────────────────────────────────────────
    total_sale_oc = fields.Float(string='Thành tiền (trước CK, trước thuế)', readonly=True)
    total_discount_oc = fields.Float(string='Tiền chiết khấu', readonly=True)
    total_net_oc = fields.Float(string='Chưa có thuế', readonly=True)
    total_vat_oc = fields.Float(string='Tiền thuế GTGT', readonly=True)
    total_amount_oc = fields.Float(string='Tổng cộng tiền thanh toán', readonly=True)
    total_amount_in_words = fields.Char(string='Số tiền bằng chữ', readonly=True)

    # ── Dòng hàng hóa (chỉ đọc) ──────────────────────────────────────────────
    line_ids = fields.One2many(
        'meinvoice.publish.wizard.line', 'wizard_id', string='Chi tiết hàng hóa', readonly=True,
    )

    # ── JSON đầy đủ lưu tạm để submit ─────────────────────────────────────────
    invoice_data_json = fields.Text(string='Invoice Data JSON (ẩn)')

    def action_confirm_publish(self):
        """Lấy dữ liệu wizard, patch buyer fields, gửi lên meInvoice API."""
        self.ensure_one()
        order = self.sale_order_id
        if not order:
            raise UserError('Không tìm được đơn hàng.')

        # Lấy invoice_data gốc đã tính sẵn
        try:
            invoice_data = json.loads(self.invoice_data_json or '{}')
        except Exception:
            raise UserError('Dữ liệu hóa đơn bị hỏng. Vui lòng đóng wizard và thử lại.')

        # Patch các trường người dùng đã chỉnh
        from datetime import date
        inv_date = self.inv_date
        invoice_data['InvSeries'] = (self.inv_series or '').strip()
        invoice_data['InvDate'] = inv_date.strftime('%Y-%m-%d') if inv_date else invoice_data.get('InvDate', '')
        invoice_data['PaymentMethodName'] = (self.payment_method or 'TM/CK').strip()
        invoice_data['BuyerLegalName'] = (self.buyer_legal_name or '').strip()
        invoice_data['BuyerFullName'] = (self.buyer_full_name or '').strip()
        invoice_data['BuyerTaxCode'] = (self.buyer_tax_code or '').strip()
        invoice_data['BuyerAddress'] = (self.buyer_address or '').strip()
        invoice_data['BuyerPhoneNumber'] = (self.buyer_phone or '').strip()
        invoice_data['BuyerEmail'] = (self.buyer_email or '').strip()

        # Cập nhật IsInvoiceCalculatingMachine theo series mới
        new_series = invoice_data['InvSeries']
        invoice_data['IsInvoiceCalculatingMachine'] = (
            len(new_series) >= 5 and new_series[4].upper() == 'M'
        )

        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        results = config.push_meinvoice_invoice([invoice_data])

        transaction_id = ''
        inv_no = ''
        inv_code = ''
        inv_series_result = ''
        inv_date_saved = False
        if results and isinstance(results, list):
            first = results[0] if results else {}
            transaction_id = str(first.get('TransactionID') or '')
            inv_no = str(first.get('InvNo') or '')
            inv_code = str(first.get('InvCode') or '')
            inv_series_result = str(first.get('InvSeries') or '')
            raw_date = first.get('InvDate') or ''
            if raw_date:
                try:
                    inv_date_saved = str(raw_date)[:10]
                except Exception:
                    inv_date_saved = False
            err_code = first.get('ErrorCode') or ''
            if err_code:
                raise UserError('meInvoice phát hành lỗi: %s' % err_code)

        order.sudo().write({
            'misa_meinvoice_synced': True,
            'misa_meinvoice_transaction_id': transaction_id,
            'misa_meinvoice_inv_no': inv_no,
            'misa_meinvoice_inv_code': inv_code,
            'misa_meinvoice_inv_series': inv_series_result or new_series,
            'misa_meinvoice_inv_date': inv_date_saved or (inv_date.strftime('%Y-%m-%d') if inv_date else False),
        })
        _logger.info(
            'meInvoice published (wizard) for SO %s: TransactionID=%s InvNo=%s',
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


class MeinvoicePublishWizardLine(models.TransientModel):
    _name = 'meinvoice.publish.wizard.line'
    _description = 'Dòng hàng hóa xem trước hóa đơn'

    wizard_id = fields.Many2one('meinvoice.publish.wizard', ondelete='cascade')
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
