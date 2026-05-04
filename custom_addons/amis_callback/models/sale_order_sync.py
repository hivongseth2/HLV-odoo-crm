# -*- coding: utf-8 -*-
import uuid
import logging
from datetime import datetime

from odoo import fields, models
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

        for idx, line in enumerate(
            self.order_line.filtered(lambda l: not l.display_type and l.product_uom_qty > 0),
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
                'inventory_item_name': product.name,
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
            'is_created_savoucher': 1 if self.misa_sa_voucher_org_refid else 0,
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
