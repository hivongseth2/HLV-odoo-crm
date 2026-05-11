# -*- coding: utf-8 -*-
import re
import uuid
import logging
from datetime import datetime

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SaleOrderAmisSync(models.Model):
    _inherit = 'sale.order'

    misa_sa_voucher_synced = fields.Boolean(
        string='Đã sync SAVoucher MISA',
        default=False,
        copy=False,
        help='SAVoucher (đơn bán hàng, voucher_type=13) đã được đẩy lên MISA.',
    )
    misa_sa_voucher_org_refid = fields.Char(
        string='MISA org_refid SAVoucher',
        copy=False,
        help='org_refid dùng khi push SAVoucher lên MISA.',
    )
    misa_sa_invoice_synced = fields.Boolean(
        string='Đã sync SAInvoice MISA',
        default=False,
        copy=False,
        help='SAInvoice (hóa đơn bán hàng, voucher_type=11) đã được đẩy lên MISA.',
    )
    misa_sa_invoice_org_refid = fields.Char(
        string='MISA org_refid SAInvoice',
        copy=False,
        help='org_refid dùng khi push SAInvoice lên MISA.',
    )

    # ── meInvoice (Hóa đơn điện tử đầu ra) ─────────────────────────────────
    misa_meinvoice_synced = fields.Boolean(
        string='Đã phát hành HĐĐT meInvoice',
        default=False,
        copy=False,
        help='Hóa đơn điện tử đã được phát hành qua MISA meInvoice API.',
    )
    misa_meinvoice_ref_id = fields.Char(
        string='meInvoice RefID',
        copy=False,
        help='RefID (uuid) dùng khi phát hành hóa đơn meInvoice (chống trùng).',
    )
    misa_meinvoice_transaction_id = fields.Char(
        string='meInvoice Transaction ID',
        copy=False,
        help='Mã tra cứu hóa đơn (TransactionID) do hệ thống meInvoice cấp sau khi phát hành.',
    )
    misa_meinvoice_inv_no = fields.Char(
        string='Số hóa đơn meInvoice',
        copy=False,
        help='Số hóa đơn được meInvoice cấp sau khi phát hành thành công.',
    )
    misa_meinvoice_inv_code = fields.Char(
        string='Mã hóa đơn CQT',
        copy=False,
        help='Mã tra cứu hóa đơn do Cơ quan Thuế cấp (InvCode).',
    )
    misa_meinvoice_inv_series = fields.Char(
        string='Ký hiệu hóa đơn',
        copy=False,
        help='Ký hiệu (series) hóa đơn điện tử.',
    )
    misa_meinvoice_inv_date = fields.Date(
        string='Ngày hóa đơn',
        copy=False,
        help='Ngày phát hành hóa đơn điện tử.',
    )

    # ── Thông tin xuất hóa đơn điền trước (pre-fill) ─────────────────────────
    meinvoice_prefill_buyer_legal_name = fields.Char(
        string='Tên đơn vị (pháp lý)',
        copy=False,
        help='Tên đơn vị mua hàng theo pháp lý. Ưu tiên điền vào hóa đơn nháp.',
    )
    meinvoice_prefill_buyer_full_name = fields.Char(
        string='Họ tên người nhận HĐ',
        copy=False,
        help='Họ tên người mua hoặc người nhận hóa đơn.',
    )
    meinvoice_prefill_buyer_tax_code = fields.Char(
        string='MST người mua',
        copy=False,
        help='Mã số thuế của đơn vị mua hàng.',
    )
    meinvoice_prefill_buyer_address = fields.Char(
        string='Địa chỉ người mua',
        copy=False,
        help='Địa chỉ đầy đủ của đơn vị mua hàng.',
    )
    meinvoice_prefill_buyer_phone = fields.Char(
        string='SĐT người mua',
        copy=False,
    )
    meinvoice_prefill_buyer_email = fields.Char(
        string='Email người mua',
        copy=False,
    )
    meinvoice_prefill_payment_method = fields.Char(
        string='Phương thức TT',
        copy=False,
        default='TM/CK',
    )
    meinvoice_prefill_inv_series = fields.Char(
        string='Ký hiệu HĐ (override)',
        copy=False,
        help='Ghi đè ký hiệu hóa đơn lấy từ cấu hình meInvoice.',
    )

    # ── Liên kết hóa đơn điện tử nháp ─────────────────────────────────────────
    amis_draft_invoice_ids = fields.One2many(
        'meinvoice.invoice', 'sale_order_id', string='Hóa đơn điện tử (nháp)',
    )
    amis_draft_invoice_count = fields.Integer(
        compute='_compute_amis_draft_invoice_count', string='Số HĐĐT',
    )

    @api.depends('amis_draft_invoice_ids')
    def _compute_amis_draft_invoice_count(self):
        for order in self:
            order.amis_draft_invoice_count = len(order.amis_draft_invoice_ids)

    def action_confirm(self):
        """Override: sau khi xác nhận, tự động tạo HĐ nháp meInvoice cho đơn Shopee."""
        res = super().action_confirm()
        for order in self:
            if order.state in ('sale', 'done'):
                order._auto_create_shopee_meinvoice_draft()
        return res

    def _auto_create_shopee_meinvoice_draft(self):
        """Tự động tạo hóa đơn điện tử nháp nếu đây là đơn Shopee và config cho phép."""
        self.ensure_one()

        # Chỉ xử lý khi có shopee_order_ref
        if not (getattr(self, 'shopee_order_ref', None) or ''):
            return

        config = self.env['amis.callback.config'].sudo().search([], limit=1, order='id asc')
        if not config or not config.meinvoice_enabled:
            return
        if not config.meinvoice_auto_draft_on_confirm:
            return

        # Không tạo nếu đã có nháp
        existing = self.env['meinvoice.invoice'].sudo().search([
            ('sale_order_id', '=', self.id),
            ('state', '=', 'draft'),
        ], limit=1)
        if existing:
            _logger.info(
                'Skip auto-draft meInvoice for SO %s: đã có nháp id=%d', self.name, existing.id
            )
            return

        try:
            import json as _json
            from datetime import date as _date

            invoice_data = self._build_meinvoice_invoice_data(config)

            buyer_full_name = config.get_meinvoice_buyer_name(self)
            shipping = self.partner_shipping_id
            shopee_addr = (getattr(shipping, 'street', '') or '').strip()
            buyer_address = (
                shopee_addr
                or config.meinvoice_shopee_default_address
                or 'Khách hàng không cung cấp thông tin'
            ).strip()

            inv_series = (self.meinvoice_prefill_inv_series or invoice_data.get('InvSeries', '')).strip()
            payment_method = (self.meinvoice_prefill_payment_method or invoice_data.get('PaymentMethodName', 'TM/CK')).strip()

            inv_date_str = invoice_data.get('InvDate', '')
            try:
                inv_date = _date.fromisoformat(inv_date_str)
            except Exception:
                inv_date = _date.today()

            line_vals = []
            for item in invoice_data.get('OriginalInvoiceDetail', []):
                line_vals.append((0, 0, {
                    'sort_order': item.get('SortOrder', 0),
                    'item_code': item.get('ItemCode', ''),
                    'item_name': item.get('ItemName', ''),
                    'unit_name': item.get('UnitName', ''),
                    'quantity': item.get('Quantity', 0),
                    'unit_price': item.get('UnitPrice', 0),
                    'discount_rate': item.get('DiscountRate', 0),
                    'discount_amount_oc': item.get('DiscountAmountOC', 0),
                    'amount_oc': item.get('AmountOC', 0),
                    'amount_without_vat_oc': item.get('AmountWithoutVATOC', 0),
                    'vat_rate_name': item.get('VATRateName', ''),
                    'vat_amount_oc': item.get('VATAmountOC', 0),
                }))

            draft = self.env['meinvoice.invoice'].sudo().create({
                'sale_order_id': self.id,
                'inv_series': inv_series,
                'inv_date': inv_date,
                'payment_method': payment_method,
                'buyer_legal_name': '',  # để trống cho đơn Shopee
                'buyer_full_name': buyer_full_name,
                'buyer_tax_code': '',
                'buyer_address': buyer_address,
                'buyer_phone': '',
                'buyer_email': '',
                'total_sale_oc': invoice_data.get('TotalSaleAmountOC', 0),
                'total_discount_oc': invoice_data.get('TotalDiscountAmountOC', 0),
                'total_net_oc': invoice_data.get('TotalAmountWithoutVATOC', 0),
                'total_vat_oc': invoice_data.get('TotalVATAmountOC', 0),
                'total_amount_oc': invoice_data.get('TotalAmountOC', 0),
                'total_amount_in_words': invoice_data.get('TotalAmountInWords', ''),
                'line_ids': line_vals,
                'invoice_data_json': _json.dumps(invoice_data, ensure_ascii=False, default=str),
            })
            _logger.info(
                'Auto-created meInvoice draft id=%d for Shopee SO %s', draft.id, self.name
            )
        except Exception:
            _logger.exception(
                'Auto-create meInvoice draft failed for SO %s — bỏ qua, không block xác nhận đơn.',
                self.name,
            )

    def action_sync_misa_sa_invoice(self):
        """Tạo job sync hóa đơn bán hàng (SAInvoice) lên MISA — được gọi bởi nút bấm."""
        for order in self:
            if order.state not in ('sale', 'done'):
                raise UserError(
                    'Đơn hàng "%s" phải ở trạng thái Đã xác nhận hoặc Hoàn thành.' % order.name
                )
            if order.misa_sa_invoice_synced:
                raise UserError('Đơn hàng "%s" đã được sync SAInvoice lên MISA rồi.' % order.name)

            config = self.env['amis.callback.config'].sudo().ensure_singleton()
            if not config.sync_outgoing_so_enabled:
                raise UserError('Tính năng đồng bộ xuất kho / bán hàng MISA chưa được bật trong cấu hình.')

            existing = self.env['amis.sync.job'].sudo().search([
                ('sale_order_id', '=', order.id),
                ('direction', '=', 'sa_invoice'),
                ('status', '=', 'pending'),
            ], limit=1)
            if existing:
                raise UserError('Đơn hàng "%s" đã có job SAInvoice đang chờ xử lý.' % order.name)

            self.env['amis.sync.job'].sudo().create({
                'sale_order_id': order.id,
                'direction': 'sa_invoice',
                'status': 'pending',
            })
            _logger.info('AMIS SAInvoice job enqueued for SO %s', order.name)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Đã enqueue',
                'message': 'SAInvoice sẽ được đồng bộ lên MISA trong vài giây.',
                'type': 'success',
                'sticky': False,
            },
        }

    def _sync_sa_invoice_to_misa(self):
        """Được gọi bởi queue job — push SAInvoice lên MISA."""
        self.ensure_one()
        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        config.ensure_sync_ready()

        if self.misa_sa_invoice_synced:
            _logger.info('Skip SAInvoice for SO %s: đã sync rồi.', self.name)
            return

        # Lọc theo cấu hình: chỉ sync đơn Shopee hoặc tất cả đơn
        has_shopee_ref = bool(getattr(self, 'shopee_order_ref', None))
        if config.sync_shopee_only and not has_shopee_ref:
            _logger.info('Skip SAInvoice for SO %s: không có shopee_order_ref (chế độ chỉ sync Shopee).', self.name)
            return

        partner = self.partner_id

        # Resolve account_object qua config (logic chung với SAVoucher)
        account_object_id, account_object_code, account_object_name = \
            config.resolve_misa_account_object(partner, sale_order=self)

        branch_id = (config.misa_branch_id or '').strip()
        if not branch_id:
            raise UserError('Thiếu MISA Branch ID trong cấu hình.')

        sa_invoice_refid = (self.misa_sa_invoice_org_refid or '').strip()
        if not sa_invoice_refid:
            sa_invoice_refid = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'sa_invoice|%d' % self.id))

        detail = []
        total_gross = 0.0
        total_discount = 0.0
        total_vat = 0.0

        # --- Kiểm tra tất cả sản phẩm đã có MISA mapping chưa ---
        lines_to_sync = self.order_line.filtered(lambda l: not l.display_type and l.product_uom_qty > 0)
        unmapped = [
            l.product_id.display_name
            for l in lines_to_sync
            if not (l.product_id.misa_inventory_item_id or '').strip()
        ]
        if unmapped:
            raise UserError(
                'Đơn hàng "%s" có sản phẩm chưa được map với MISA, không thể đồng bộ:\n%s\n\n'
                'Vui lòng bấm "Đồng bộ sản phẩm mới" trong Cấu hình AMIS để cập nhật mapping.'
                % (self.name, '\n'.join('• ' + n for n in unmapped))
            )

        for idx, line in enumerate(
            lines_to_sync,
            start=1,
        ):
            product = line.product_id
            qty = float(line.qty_delivered) if float(line.qty_delivered) > 0 else float(line.product_uom_qty)
            price_unit_with_tax = float(line.price_unit)  # Đơn giá đã có thuế (Odoo lưu có thuế)
            discount = float(line.discount or 0.0)

            # Lấy thuế suất trước để tính ngược giá trước thuế
            vat_rate = 0.0
            for tax in line.tax_id:
                if tax.amount_type == 'percent':
                    vat_rate = float(tax.amount)
                    break

            # Đơn giá trước thuế = Đơn giá (đã có thuế) / (1 + Thuế suất)
            price_before_tax = price_unit_with_tax / (1.0 + vat_rate / 100.0) if vat_rate else price_unit_with_tax

            # Thành tiền (trước CK, trước thuế) = Đơn giá trước thuế * Số lượng
            amount_oc = price_before_tax * qty

            # Tiền CK = Thành tiền * Tỷ lệ CK
            discount_amount = amount_oc * discount / 100.0

            # Tiền thuế tính trên (Thành tiền - Tiền CK)
            net_amount = amount_oc - discount_amount
            vat_amount = net_amount * vat_rate / 100.0

            total_gross += amount_oc
            total_discount += discount_amount
            total_vat += vat_amount

            inventory_item_id = (product.misa_inventory_item_id or '').strip()
            unit_id = (line.product_uom.misa_unit_id or '').strip()

            ref_detail_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'sa_inv_detail|%d|%d' % (self.id, line.id)))

            detail.append({
                'ref_detail_id': ref_detail_id,
                'refid': sa_invoice_refid,
                'inventory_item_id': inventory_item_id,
                'unit_id': unit_id,
                'main_unit_id': unit_id,
                'sort_order': idx,
                'is_promotion': False,
                'not_in_vat_declaration': False,
                'quantity': qty,
                'unit_price': price_before_tax,
                'unit_price_after_tax': price_unit_with_tax,
                'amount_oc': amount_oc,
                'amount': amount_oc,
                'discount_rate': discount,
                'discount_amount_oc': discount_amount,
                'discount_amount': discount_amount,
                'vat_rate': vat_rate,
                'vat_amount_oc': vat_amount,
                'vat_amount': vat_amount,
                'main_convert_rate': 1.0,
                'main_quantity': qty,
                'amount_after_tax': net_amount + vat_amount,
                'description': product.name,
                'debit_account': '131',
                'credit_account': '5111',
                'vat_account': '3331',
                'vat_description': 'Thue GTGT - %s' % product.name,
                'exchange_rate_operator': '*',
                'account_object_id': account_object_id,
                'account_object_name': account_object_name,
                'account_object_code': account_object_code,
                'account_object_address': partner.contact_address_complete if partner else '',
                'inventory_item_code': product.default_code or str(product.id),
                'inventory_item_type': 0,
                'unit_name': line.product_uom.name,
                'main_unit_name': line.product_uom.name,
                'inventory_item_name': re.sub(r'^\[.*?\]\s*', '', product.name or ''),
                'is_follow_serial_number': False,
                'is_allow_duplicate_serial_number': False,
                'is_unit_price_after_tax': False,
                'is_description': False,
                'is_description_import': False,
                'discount_type': 1,
                'state': 0,
            })

        total_sale = total_gross - total_discount
        total_amount = total_sale + total_vat
        refdate = self._to_misa_date(datetime.utcnow())

        voucher = {
            'voucher_type': 11,
            'is_get_new_id': True,
            'org_refid': sa_invoice_refid,
            'is_allow_group': False,
            'org_refno': self.name,
            'org_reftype': 3560,
            'org_reftype_name': 'SAInvoice',
            'refid': sa_invoice_refid,
            'act_voucher_type': 0,
            'reftype': 3560,
            'reftype_name': 'Hoa don ban hang',
            'branch_id': branch_id,
            'account_object_id': account_object_id,
            'display_on_book': 0,
            'discount_type': 1,
            'discount_rate_voucher': 0.0,
            'inv_type_id': 1,
            'inv_date': refdate,
            'is_paid': False,
            'is_posted': True,
            'include_invoice': 1 if config.sa_invoice_include_vat else 0,
            'invoice_template_id': (config.misa_inv_template_id or '').strip() if config.sa_invoice_include_vat else None,
            'inv_series': (config.misa_inv_series or '').strip() if config.sa_invoice_include_vat else None,
            'is_increase_invno': True if config.sa_invoice_include_vat else False,
            'is_attach_list': False,
            'is_branch_issued': False,
            'is_posted_last_year': False,
            'is_invoice_replace': False,
            'exchange_rate': 1.0,
            'total_sale_amount_oc': total_gross,
            'total_sale_amount': total_gross,
            'total_discount_amount_oc': total_discount,
            'total_discount_amount': total_discount,
            'total_vat_amount_oc': total_vat,
            'total_vat_amount': total_vat,
            'total_amount_oc': total_amount,
            'total_amount': total_amount,
            'account_object_name': account_object_name,
            'account_object_code': account_object_code,
            'account_object_address': partner.contact_address_complete if partner else '',
            'account_object_tax_code': (partner.vat or '') if partner else '',
            'payment_method': 'TM/CK',
            'buyer': partner.display_name if partner else '',
            'currency_id': self.currency_id.name or 'VND',
            'refno_finance': '',
            'refno_management': '',
            'send_email_status': 0,
            'is_invoice_receipted': False,
            'invoice_status': 0,
            'is_invoice_deleted': False,
            'is_update_template': False,
            'ccy_exchange_operator': False,
            'auto_refno': False,
            'publish_status': 0,
            'state': 0,
            'detail': detail,
        }

        config.push_sa_invoice(voucher)

        self.sudo().write({
            'misa_sa_invoice_synced': True,
            'misa_sa_invoice_org_refid': sa_invoice_refid,
        })
        _logger.info('SAInvoice synced for SO %s, org_refid=%s', self.name, sa_invoice_refid)

    def action_reset_misa_sa_invoice(self):
        """Reset cờ SAInvoice để cho phép sync lại (dùng khi MISA báo lỗi async)."""
        for order in self:
            order.sudo().write({
                'misa_sa_invoice_synced': False,
                'misa_sa_invoice_org_refid': False,
            })
            # Xóa job sa_invoice cũ nếu còn
            self.env['amis.sync.job'].sudo().search([
                ('sale_order_id', '=', order.id),
                ('direction', '=', 'sa_invoice'),
            ]).unlink()
        return True

    def _to_misa_date(self, value):
        if not value:
            value = datetime.utcnow()
        if hasattr(value, 'strftime'):
            return value.strftime('%Y-%m-%d')
        return str(value)[:10]

    # ── meInvoice: Phát hành hóa đơn điện tử ──────────────────────────────────

    def action_publish_meinvoice_invoice(self):
        """Tạo hóa đơn điện tử nháp từ đơn hàng và mở để chỉnh sửa trước khi gửi CQT."""
        self.ensure_one()
        if self.state not in ('sale', 'done'):
            raise UserError('Đơn hàng phải ở trạng thái Đã xác nhận hoặc Hoàn thành.')

        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        if not config.meinvoice_enabled:
            raise UserError('Tính năng phát hành HĐĐT meInvoice chưa được bật trong cấu hình.')

        # Kiểm tra hóa đơn nháp chưa xử lý
        existing_draft = self.env['meinvoice.invoice'].search([
            ('sale_order_id', '=', self.id),
            ('state', '=', 'draft'),
        ], limit=1)
        if existing_draft:
            raise UserError(
                'Đã có hóa đơn nháp cho đơn hàng này. '
                'Vui lòng hoàn thành hoặc hủy hóa đơn nháp hiện tại trước khi tạo mới.'
            )

        # Tính invoice_data từ SO
        invoice_data = self._build_meinvoice_invoice_data(config)

        is_shopee = bool(getattr(self, 'shopee_order_ref', None))

        if is_shopee:
            # Đơn Shopee: tên đơn vị pháp lý để trống, tên người mua lấy theo kênh shop
            buyer_legal_name = ''
            buyer_full_name = config.get_meinvoice_buyer_name(self)
            buyer_tax_code = ''
            # Địa chỉ lấy từ địa chỉ giao hàng Shopee (partner_shipping_id.street)
            shipping = self.partner_shipping_id
            shopee_addr = (getattr(shipping, 'street', '') or '').strip()
            buyer_address = (
                self.meinvoice_prefill_buyer_address
                or shopee_addr
                or config.meinvoice_shopee_default_address
                or 'Khách hàng không cung cấp thông tin'
            ).strip()
            buyer_phone = (getattr(shipping, 'phone', '') or '').strip()
            buyer_email = ''
        else:
            # Ưu tiên thông tin từ pre-fill trên SO; nếu trống thì lấy từ dữ liệu tính toán
            buyer_legal_name = (
                self.meinvoice_prefill_buyer_legal_name or invoice_data.get('BuyerLegalName', '')
            ).strip()
            buyer_full_name = (
                self.meinvoice_prefill_buyer_full_name or invoice_data.get('BuyerFullName', '')
            ).strip()
            buyer_tax_code = (
                self.meinvoice_prefill_buyer_tax_code or invoice_data.get('BuyerTaxCode', '')
            ).strip()
            buyer_address = (
                self.meinvoice_prefill_buyer_address or invoice_data.get('BuyerAddress', '')
            ).strip()
            buyer_phone = (
                self.meinvoice_prefill_buyer_phone or invoice_data.get('BuyerPhoneNumber', '')
            ).strip()
            buyer_email = (
                self.meinvoice_prefill_buyer_email or invoice_data.get('BuyerEmail', '')
            ).strip()
        inv_series = (
            self.meinvoice_prefill_inv_series or invoice_data.get('InvSeries', '')
        ).strip()
        payment_method = (
            self.meinvoice_prefill_payment_method or invoice_data.get('PaymentMethodName', 'TM/CK')
        ).strip()

        # Tạo dòng hàng hóa từ OriginalInvoiceDetail
        line_vals = []
        for item in invoice_data.get('OriginalInvoiceDetail', []):
            line_vals.append((0, 0, {
                'sort_order': item.get('SortOrder', 0),
                'item_code': item.get('ItemCode', ''),
                'item_name': item.get('ItemName', ''),
                'unit_name': item.get('UnitName', ''),
                'quantity': item.get('Quantity', 0),
                'unit_price': item.get('UnitPrice', 0),
                'discount_rate': item.get('DiscountRate', 0),
                'discount_amount_oc': item.get('DiscountAmountOC', 0),
                'amount_oc': item.get('AmountOC', 0),
                'amount_without_vat_oc': item.get('AmountWithoutVATOC', 0),
                'vat_rate_name': item.get('VATRateName', ''),
                'vat_amount_oc': item.get('VATAmountOC', 0),
            }))

        from datetime import date as _date
        inv_date_str = invoice_data.get('InvDate', '')
        try:
            inv_date = _date.fromisoformat(inv_date_str)
        except Exception:
            inv_date = _date.today()

        import json as _json
        draft = self.env['meinvoice.invoice'].create({
            'sale_order_id': self.id,
            'inv_series': inv_series,
            'inv_date': inv_date,
            'payment_method': payment_method,
            'buyer_legal_name': buyer_legal_name,
            'buyer_full_name': buyer_full_name,
            'buyer_tax_code': buyer_tax_code,
            'buyer_address': buyer_address,
            'buyer_phone': buyer_phone,
            'buyer_email': buyer_email,
            'total_sale_oc': invoice_data.get('TotalSaleAmountOC', 0),
            'total_discount_oc': invoice_data.get('TotalDiscountAmountOC', 0),
            'total_net_oc': invoice_data.get('TotalAmountWithoutVATOC', 0),
            'total_vat_oc': invoice_data.get('TotalVATAmountOC', 0),
            'total_amount_oc': invoice_data.get('TotalAmountOC', 0),
            'total_amount_in_words': invoice_data.get('TotalAmountInWords', ''),
            'line_ids': line_vals,
            'invoice_data_json': _json.dumps(invoice_data, ensure_ascii=False, default=str),
        })
        _logger.info('meInvoice draft created for SO %s → meinvoice.invoice id=%d', self.name, draft.id)

        return {
            'type': 'ir.actions.act_window',
            'name': 'Hóa đơn điện tử — %s' % self.name,
            'res_model': 'meinvoice.invoice',
            'res_id': draft.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_meinvoice_drafts(self):
        """Mở danh sách hóa đơn điện tử của đơn hàng này."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Hóa đơn điện tử — %s' % self.name,
            'res_model': 'meinvoice.invoice',
            'view_mode': 'list,form',
            'domain': [('sale_order_id', '=', self.id)],
            'context': {'default_sale_order_id': self.id},
        }

    def action_view_meinvoice_invoice(self):
        """Lấy link xem hóa đơn đã phát hành từ meInvoice và mở trên trình duyệt."""
        self.ensure_one()
        if not self.misa_meinvoice_synced or not self.misa_meinvoice_transaction_id:
            raise UserError('Đơn hàng chưa phát hành hóa đơn meInvoice hoặc thiếu TransactionID.')

        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        view_url = config.get_meinvoice_publishview_url([self.misa_meinvoice_transaction_id])
        if not view_url:
            raise UserError('meInvoice không trả về link xem hóa đơn.')

        return {
            'type': 'ir.actions.act_url',
            'url': view_url,
            'target': 'new',
        }

    def action_reset_meinvoice_invoice(self):
        """Reset cờ meInvoice để phát hành lại (dùng khi phát hành lỗi)."""
        for order in self:
            order.sudo().write({
                'misa_meinvoice_synced': False,
                'misa_meinvoice_transaction_id': False,
                'misa_meinvoice_inv_no': False,
                'misa_meinvoice_inv_code': False,
                'misa_meinvoice_inv_series': False,
                'misa_meinvoice_inv_date': False,
            })
        return True

    def _publish_meinvoice_invoice(self):
        """Xây dựng InvoiceData và gọi meInvoice API phát hành hóa đơn điện tử."""
        self.ensure_one()
        config = self.env['amis.callback.config'].sudo().ensure_singleton()

        if self.misa_meinvoice_synced:
            _logger.info('Skip meInvoice publish for SO %s: đã phát hành rồi.', self.name)
            return

        if not config.meinvoice_enabled:
            _logger.info('Skip meInvoice publish for SO %s: tính năng chưa bật.', self.name)
            return

        if config.meinvoice_shopee_only and not (getattr(self, 'shopee_order_ref', None) or ''):
            _logger.info(
                'Skip meInvoice publish for SO %s: đơn không có shopee_order_ref (chế độ chỉ sync Shopee).',
                self.name,
            )
            return

        invoice_data = self._build_meinvoice_invoice_data(config)
        _logger.info(
            'meInvoice invoice payload for SO %s:\n%s',
            self.name,
            __import__('json').dumps(invoice_data, ensure_ascii=False, default=str, indent=2),
        )

        results = config.push_meinvoice_invoice([invoice_data])

        transaction_id = ''
        inv_no = ''
        inv_code = ''
        inv_series = ''
        inv_date = False
        if results and isinstance(results, list):
            first = results[0] if results else {}
            transaction_id = str(first.get('TransactionID') or first.get('transactionID') or '')
            inv_no = str(first.get('InvNo') or first.get('invNo') or '')
            inv_code = str(first.get('InvCode') or first.get('invCode') or '')
            inv_series = str(first.get('InvSeries') or first.get('invSeries') or '')
            raw_date = first.get('InvDate') or first.get('invDate') or ''
            if raw_date:
                try:
                    inv_date = str(raw_date)[:10]  # lấy phần YYYY-MM-DD
                except Exception:
                    inv_date = False
            err_code = first.get('ErrorCode') or first.get('errorCode') or ''
            if err_code:
                raise UserError('meInvoice phát hành lỗi: %s' % err_code)

        self.sudo().write({
            'misa_meinvoice_synced': True,
            'misa_meinvoice_transaction_id': transaction_id,
            'misa_meinvoice_inv_no': inv_no,
            'misa_meinvoice_inv_code': inv_code,
            'misa_meinvoice_inv_series': inv_series,
            'misa_meinvoice_inv_date': inv_date,
        })
        _logger.info(
            'meInvoice published for SO %s: TransactionID=%s InvNo=%s',
            self.name, transaction_id, inv_no,
        )

    def _build_meinvoice_invoice_data(self, config):
        """Xây dựng đối tượng InvoiceData theo spec MISA meInvoice Đầu ra."""
        self.ensure_one()

        inv_series = (config.meinvoice_inv_series or '').strip()
        if not inv_series:
            raise UserError('Thiếu Ký hiệu hóa đơn (meInvoice) trong cấu hình.')

        # Hóa đơn MTT: ký tự thứ 5 (index 4) là 'M'
        is_mtt = len(inv_series) >= 5 and inv_series[4].upper() == 'M'
        # Phiếu xuất kho: ký tự đầu tiên là '6' (theo spec meInvoice)
        is_pxk = inv_series[0] == '6'

        # RefID (idempotent)
        ref_id = (self.misa_meinvoice_ref_id or '').strip()
        if not ref_id:
            ref_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'meinvoice|%d' % self.id))
            self.sudo().write({'misa_meinvoice_ref_id': ref_id})

        partner = self.partner_id
        inv_date = self._to_misa_date(datetime.utcnow())

        # Tên người mua: dùng tên mặc định theo kênh Shopee nếu có config
        buyer_name = config.get_meinvoice_buyer_name(self)

        lines = self.order_line.filtered(lambda l: not l.display_type and l.product_uom_qty > 0)
        if not lines:
            raise UserError('Đơn hàng "%s" không có dòng sản phẩm hợp lệ để phát hành hóa đơn.' % self.name)

        # ── Tính toán từng dòng ──────────────────────────────────────────────
        detail = []
        total_sale_oc = 0.0
        total_discount_oc = 0.0
        total_vat_oc = 0.0
        tax_groups = {}  # {vat_rate_name: {'AmountWithoutVATOC': ..., 'VATAmountOC': ...}}

        for idx, line in enumerate(lines, start=1):
            product = line.product_id
            qty = float(line.product_uom_qty)
            price_with_tax = float(line.price_unit)
            discount = float(line.discount or 0.0)

            vat_rate = 0.0
            for tax in line.tax_id:
                if tax.amount_type == 'percent':
                    vat_rate = float(tax.amount)
                    break

            price_before_tax = price_with_tax / (1.0 + vat_rate / 100.0) if vat_rate else price_with_tax
            amount_oc = round(price_before_tax * qty, 2)
            discount_oc = round(amount_oc * discount / 100.0, 2)
            net_oc = round(amount_oc - discount_oc, 2)
            vat_oc = round(net_oc * vat_rate / 100.0, 2)

            total_sale_oc += amount_oc
            total_discount_oc += discount_oc
            total_vat_oc += vat_oc

            # Xác định VATRateName theo spec meInvoice
            if vat_rate == 0.0:
                vat_rate_name = '0%'
            elif vat_rate == 5.0:
                vat_rate_name = '5%'
            elif vat_rate == 8.0:
                vat_rate_name = '8%'
            elif vat_rate == 10.0:
                vat_rate_name = '10%'
            elif vat_rate < 0:
                vat_rate_name = 'KKKNT'
            else:
                vat_rate_name = 'KHAC:%.1f%%' % vat_rate

            # Nhóm thuế cho TaxRateInfo
            tg = tax_groups.setdefault(vat_rate_name, {'AmountWithoutVATOC': 0.0, 'VATAmountOC': 0.0})
            tg['AmountWithoutVATOC'] = round(tg['AmountWithoutVATOC'] + net_oc, 2)
            tg['VATAmountOC'] = round(tg['VATAmountOC'] + vat_oc, 2)

            item_name = re.sub(r'^\[.*?\]\s*', '', product.name or '')
            detail.append({
                'ItemType': 1,
                'SortOrder': idx,
                'LineNumber': idx,
                'ItemCode': product.default_code or '',
                'ItemName': item_name,
                'UnitName': line.product_uom.name or '',
                'Quantity': qty,
                'UnitPrice': round(price_before_tax, 2),
                'AmountOC': amount_oc,
                'Amount': amount_oc,
                'DiscountRate': discount,
                'DiscountAmountOC': discount_oc,
                'DiscountAmount': discount_oc,
                'AmountWithoutVATOC': net_oc,
                'AmountWithoutVAT': net_oc,
                'VATRateName': vat_rate_name,
                'VATAmountOC': vat_oc,
                'VATAmount': vat_oc,
            })

        total_sale_oc = round(total_sale_oc, 2)
        total_discount_oc = round(total_discount_oc, 2)
        total_vat_oc = round(total_vat_oc, 2)
        total_net_oc = round(total_sale_oc - total_discount_oc, 2)
        total_amount_oc = round(total_net_oc + total_vat_oc, 2)

        tax_rate_info = [
            {
                'VATRateName': rate_name,
                'AmountWithoutVATOC': vals['AmountWithoutVATOC'],
                'VATAmountOC': vals['VATAmountOC'],
            }
            for rate_name, vals in tax_groups.items()
        ]

        company = self.company_id or self.env.company
        company_partner = company.partner_id

        invoice_data = {
            'RefID': ref_id,
            'InvSeries': inv_series,
            'InvDate': inv_date,
            'CurrencyCode': self.currency_id.name or 'VND',
            'ExchangeRate': 1.0,
            'PaymentMethodName': 'TM/CK',
            'IsInvoiceSummary': False,
            'IsInvoiceCalculatingMachine': is_mtt,
            'SellerLegalName': company.name or '',
            'SellerTaxCode': company.vat or '',
            'SellerAddress': company_partner.contact_address_complete or company.street or '',
            'SellerPhoneNumber': company.phone or '',
            'SellerEmail': company.email or '',
            'BuyerLegalName': buyer_name,
            'BuyerTaxCode': partner.vat or '',
            'BuyerAddress': partner.contact_address_complete or '',
            'BuyerFullName': buyer_name,
            'BuyerPhoneNumber': partner.phone or partner.mobile or '',
            'BuyerEmail': partner.email or '',
            'TotalSaleAmountOC': total_sale_oc,
            'TotalSaleAmount': total_sale_oc,
            'TotalDiscountAmountOC': total_discount_oc,
            'TotalDiscountAmount': total_discount_oc,
            'TotalAmountWithoutVATOC': total_net_oc,
            'TotalAmountWithoutVAT': total_net_oc,
            'TotalVATAmountOC': total_vat_oc,
            'TotalVATAmount': total_vat_oc,
            'TotalAmountOC': total_amount_oc,
            'TotalAmount': total_amount_oc,
            'TotalAmountInWords': self._amount_in_words_vi(total_amount_oc),
            'OriginalInvoiceDetail': detail,
            'TaxRateInfo': tax_rate_info,
        }
        if config.meinvoice_is_pxk or is_pxk:
            stock_out_address = (config.meinvoice_stock_out_address or '').strip() or \
                company_partner.contact_address_complete or company.street or ''
            stock_in_address = (config.meinvoice_stock_in_address or '').strip() or \
                'Khách hàng không cung cấp thông tin'
            invoice_data['StockOutAddress'] = stock_out_address
            invoice_data['StockInAddress'] = stock_in_address
            invoice_data['Transport'] = (config.meinvoice_transport_means or '').strip()
        return invoice_data

    @staticmethod
    def _amount_in_words_vi(amount):
        """Chuyển số tiền (VND) thành chữ tiếng Việt."""
        n = int(round(float(amount or 0)))
        if n == 0:
            return 'Không đồng'

        _ones = ['', 'một', 'hai', 'ba', 'bốn', 'năm', 'sáu', 'bảy', 'tám', 'chín']

        def _read_group(g, is_first=False):
            if g == 0:
                return ''
            h, r = divmod(g, 100)
            t, u = divmod(r, 10)
            parts = []
            if h:
                parts.append(_ones[h] + ' trăm')
            elif not is_first:
                parts.append('không trăm')
            if t == 1:
                s = 'mười'
                if u == 5:
                    s += ' lăm'
                elif u:
                    s += ' ' + _ones[u]
                parts.append(s)
            elif t > 1:
                s = _ones[t] + ' mươi'
                if u == 1:
                    s += ' mốt'
                elif u == 5:
                    s += ' lăm'
                elif u:
                    s += ' ' + _ones[u]
                parts.append(s)
            else:
                if u:
                    if h or not is_first:
                        parts.append('lẻ ' + _ones[u])
                    else:
                        parts.append(_ones[u])
            return ' '.join(parts)

        units = [(10 ** 9, 'tỷ'), (10 ** 6, 'triệu'), (10 ** 3, 'nghìn'), (1, '')]
        parts = []
        remaining = n
        for div, unit_name in units:
            g = remaining // div
            remaining %= div
            if g == 0:
                continue
            text = _read_group(g, is_first=not parts)
            parts.append((text + ' ' + unit_name).strip() if unit_name else text)

        result = ' '.join(parts)
        return result[:1].upper() + result[1:] + ' đồng'
