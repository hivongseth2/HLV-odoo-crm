# -*- coding: utf-8 -*-
import json
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MeinvoiceOutputInvoice(models.Model):
    """
    Hóa đơn điện tử đầu ra lấy về từ MISA meInvoice.
    Đây là bảng Odoo riêng – KHÔNG mapping vào account.move.
    """
    _name = 'meinvoice.output.invoice'
    _description = 'Hóa đơn điện tử đầu ra (meInvoice)'
    _order = 'inv_date desc, inv_no desc'
    _rec_name = 'display_name'

    # ─── Định danh từ meInvoice ───────────────────────────────────────────────
    invoice_id_misa = fields.Char(
        'InvoiceID (MISA)',
        index=True, copy=False, readonly=True,
        help='ID nội bộ meInvoice, dùng để gọi API mark accounting',
    )
    transaction_id = fields.Char(
        'Transaction ID', readonly=True, copy=False, index=True,
    )
    inv_no = fields.Char(
        'Số hóa đơn', readonly=True, copy=False, index=True,
    )
    inv_series = fields.Char('Ký hiệu', readonly=True)
    inv_date = fields.Date('Ngày hóa đơn', readonly=True, index=True)

    # ─── Thông tin khách hàng ─────────────────────────────────────────────────
    buyer_name = fields.Char('Tên khách hàng', readonly=True)
    buyer_tax_code = fields.Char('MST khách hàng', readonly=True)
    buyer_address = fields.Char('Địa chỉ', readonly=True)
    buyer_email = fields.Char('Email', readonly=True)

    # ─── Giá trị ─────────────────────────────────────────────────────────────
    currency_code = fields.Char('Ngoại tệ', default='VND', readonly=True)
    total_amount_without_vat = fields.Float('Tiền trước thuế', readonly=True, digits=(18, 0))
    total_vat_amount = fields.Float('Tiền thuế VAT', readonly=True, digits=(18, 0))
    total_amount = fields.Float('Tổng tiền', readonly=True, digits=(18, 0))
    payment_method = fields.Char('Phương thức TT', readonly=True)

    # ─── Trạng thái meInvoice ─────────────────────────────────────────────────
    inv_status = fields.Selection([
        ('1', 'Hợp lệ'),
        ('2', 'Đã hủy'),
        ('3', 'Đã thay thế'),
        ('4', 'Đã điều chỉnh'),
    ], string='Trạng thái HĐ', readonly=True, default='1')

    accounting_status = fields.Selection([
        ('0', 'Chưa hạch toán'),
        ('1', 'Đã hạch toán'),
    ], string='Hạch toán (MISA)', readonly=True, default='0', index=True)

    # ─── Trạng thái Odoo ──────────────────────────────────────────────────────
    odoo_accounting_state = fields.Selection([
        ('pending',    'Chưa xử lý'),
        ('accounted',  'Đã hạch toán'),
        ('linked',     'Đã liên kết SO'),
    ], string='Trạng thái Odoo',
       default='pending', index=True, tracking=True,
    )

    # ─── Liên kết Sale Order ──────────────────────────────────────────────────
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Sale Order',
        ondelete='set null',
        index=True,
        copy=False,
    )

    # ─── Raw data ─────────────────────────────────────────────────────────────
    raw_data = fields.Text('Raw JSON (meInvoice)', readonly=True)

    # ─── Audit ────────────────────────────────────────────────────────────────
    fetched_date = fields.Datetime('Ngày lấy về', readonly=True,
                                   default=fields.Datetime.now)
    accounted_date = fields.Datetime('Ngày hạch toán', readonly=True, copy=False)

    # ─── Compute ──────────────────────────────────────────────────────────────
    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('inv_no', 'inv_series', 'buyer_name', 'inv_date')
    def _compute_display_name(self):
        for rec in self:
            parts = filter(None, [rec.inv_series, rec.inv_no, rec.buyer_name])
            rec.display_name = ' – '.join(parts) or _('HĐ #%d') % (rec.id or 0)

    # ─── Constraints ──────────────────────────────────────────────────────────

    _sql_constraints = [
        (
            'invoice_id_misa_uniq',
            'UNIQUE(invoice_id_misa)',
            'InvoiceID từ meInvoice đã tồn tại trong hệ thống!',
        ),
    ]

    # ─── Actions ──────────────────────────────────────────────────────────────

    def action_mark_accounting(self):
        """
        Đánh dấu hạch toán lên meInvoice cho các hóa đơn được chọn.
        Gọi được từ list view (multi-select) hoặc form view (1 record).
        """
        to_process = self.filtered(
            lambda r: r.accounting_status == '0' and r.invoice_id_misa
        )
        if not to_process:
            raise UserError(_('Không có hóa đơn nào cần hạch toán (hoặc đã hạch toán rồi).'))

        invoice_ids = to_process.mapped('invoice_id_misa')
        _logger.info('Đánh dấu hạch toán %d hóa đơn: %s', len(invoice_ids), invoice_ids)

        self.env['meinvoice.output.api'].api_mark_accounting(invoice_ids)

        now = fields.Datetime.now()
        to_process.write({
            'accounting_status':    '1',
            'odoo_accounting_state': 'accounted',
            'accounted_date':        now,
        })

        # Cập nhật Sale Order liên kết
        for inv in to_process.filtered('sale_order_id'):
            inv.sale_order_id._meinvoice_check_invoiced()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title':   _('meInvoice'),
                'message': _('Đã hạch toán %d hóa đơn thành công!') % len(to_process),
                'type':    'success',
                'sticky': False,
            },
        }

    def action_link_sale_order(self):
        """
        Tìm và liên kết Sale Order phù hợp theo số hóa đơn / mã khách hàng.
        Chỉ chạy trên 1 record tại 1 thời điểm.
        """
        self.ensure_one()
        # Tìm SO theo client_order_ref = inv_no hoặc partner tax code
        so = None
        if self.inv_no:
            so = self.env['sale.order'].search(
                [('name', '=', self.inv_no)], limit=1
            ) or self.env['sale.order'].search(
                [('client_order_ref', '=', self.inv_no)], limit=1
            )
        if not so and self.buyer_tax_code:
            so = self.env['sale.order'].search(
                [('partner_id.vat', '=', self.buyer_tax_code),
                 ('state', 'in', ('sale', 'done'))],
                limit=1, order='date_order desc'
            )
        if not so:
            raise UserError(
                _('Không tìm được Sale Order phù hợp cho hóa đơn %s.\n'
                  'Vui lòng chọn thủ công ở ô "Sale Order".')
                % self.inv_no
            )
        self.write({'sale_order_id': so.id, 'odoo_accounting_state': 'linked'})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title':   _('Liên kết thành công'),
                'message': _('Đã liên kết với %s') % so.name,
                'type':    'success',
                'sticky': False,
            },
        }

    def action_view_raw(self):
        """Hiện raw JSON của hóa đơn."""
        self.ensure_one()
        try:
            pretty = json.dumps(json.loads(self.raw_data or '{}'),
                                ensure_ascii=False, indent=2)
        except Exception:
            pretty = self.raw_data or ''
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title':   _('Raw JSON – %s') % self.inv_no,
                'message': pretty[:800],
                'type':    'info',
                'sticky': True,
            },
        }

    # ─── Sync from meInvoice ──────────────────────────────────────────────────

    @api.model
    def sync_from_meinvoice(self, from_date, to_date,
                             organization_id='',
                             accounting_status=None):
        """
        Lấy hóa đơn từ meInvoice về Odoo, upsert theo invoice_id_misa.
        Trả về (created, updated, skipped).
        """
        api = self.env['meinvoice.output.api']
        page, page_size = 1, 100
        created = updated = skipped = 0

        while True:
            items, total = api.api_get_invoices(
                from_date=from_date, to_date=to_date,
                organization_id=organization_id,
                accounting_status=accounting_status,
                page_index=page, page_size=page_size,
            )
            if not items:
                break

            for item in items:
                c, u, s = self._upsert_invoice(item)
                created += c; updated += u; skipped += s

            if page * page_size >= total:
                break
            page += 1

        _logger.info(
            'meInvoice sync done: created=%d updated=%d skipped=%d',
            created, updated, skipped
        )
        return created, updated, skipped

    def _upsert_invoice(self, item):
        """Tạo hoặc cập nhật 1 bản ghi từ dict API."""
        inv_id_misa = str(
            item.get('InvoiceID') or item.get('invoiceID') or
            item.get('Id') or ''
        )
        if not inv_id_misa:
            return 0, 0, 1

        vals = self._map_api_to_vals(item)
        existing = self.search([('invoice_id_misa', '=', inv_id_misa)], limit=1)

        if existing:
            # Chỉ cập nhật nếu trạng thái hạch toán thay đổi
            if existing.accounting_status != vals.get('accounting_status', '0'):
                existing.write({'accounting_status': vals['accounting_status']})
                return 0, 1, 0
            return 0, 0, 1
        else:
            self.create(vals)
            return 1, 0, 0

    @staticmethod
    def _map_api_to_vals(item):
        """Chuyển dict API meInvoice → dict Odoo fields."""
        def _s(k, *aliases):
            for a in (k,) + aliases:
                v = item.get(a)
                if v is not None:
                    return str(v).strip()
            return ''

        def _f(k, *aliases):
            for a in (k,) + aliases:
                v = item.get(a)
                if v is not None:
                    try:
                        return float(v)
                    except Exception:
                        return 0.0
            return 0.0

        # Parse ngày
        raw_date = item.get('InvDate') or item.get('invoiceDate') or ''
        inv_date = None
        for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d', '%d/%m/%Y'):
            try:
                inv_date = fields.Date.to_date(
                    raw_date[:10].replace('/', '-')
                )
                break
            except Exception:
                pass

        acc_status = str(
            item.get('AccountingStatus') or
            item.get('accountingStatus') or '0'
        )

        return {
            'invoice_id_misa':          _s('InvoiceID', 'invoiceID', 'Id'),
            'transaction_id':           _s('TransactionID', 'transactionID'),
            'inv_no':                   _s('InvNo', 'invoiceNo', 'InvoiceNumber'),
            'inv_series':               _s('InvSeries', 'invoiceSeries', 'InvCode'),
            'inv_date':                 inv_date,
            'buyer_name':               _s('BuyerName', 'buyerName', 'CustomerName'),
            'buyer_tax_code':           _s('BuyerTaxCode', 'buyerTaxCode', 'CustomerTaxCode'),
            'buyer_address':            _s('BuyerAddress', 'buyerAddress'),
            'buyer_email':              _s('BuyerEmail', 'buyerEmail'),
            'currency_code':            _s('CurrencyCode', 'currencyCode') or 'VND',
            'total_amount_without_vat': _f('TotalAmountWithoutVAT', 'totalAmountWithoutVAT', 'AmountWithoutVAT'),
            'total_vat_amount':         _f('TotalVATAmount', 'totalVATAmount', 'VATAmount'),
            'total_amount':             _f('TotalAmount', 'totalAmount', 'Amount'),
            'payment_method':           _s('PaymentMethodName', 'paymentMethod'),
            'inv_status':               str(item.get('InvStatus') or item.get('Status') or '1'),
            'accounting_status':        acc_status,
            'raw_data':                 json.dumps(item, ensure_ascii=False, default=str),
            'fetched_date':             fields.Datetime.now(),
        }
