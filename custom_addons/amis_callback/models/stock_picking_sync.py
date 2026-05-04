# -*- coding: utf-8 -*-
import logging
import uuid
from datetime import datetime

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

ZERO_UUID = '00000000-0000-0000-0000-000000000000'


class StockPickingAmisSync(models.Model):
    _inherit = 'stock.picking'

    misa_inward_synced = fields.Boolean(
        string='Đã đồng bộ phiếu nhập MISA',
        default=False,
        copy=False,
    )
    misa_inward_org_refid = fields.Char(
        string='MISA org_refid phiếu nhập',
        copy=False,
    )

    def button_validate(self):
        res = super().button_validate()
        for picking in self:
            try:
                if picking.picking_type_code in ('incoming', 'outgoing'):
                    picking._enqueue_misa_sync(picking.picking_type_code)
            except Exception:
                _logger.exception('AMIS enqueue failed for picking %s', picking.name)
        return res

    def _enqueue_misa_sync(self, direction):
        """Tạo job trong hàng đợi amis.sync.job thay vì push trực tiếp."""
        self.ensure_one()
        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        enabled = (config.sync_incoming_po_enabled if direction == 'incoming'
                   else config.sync_outgoing_so_enabled)
        if not enabled:
            return
        # Tránh tạo job trùng nếu picking đã được enqueue và chưa xử lý
        existing = self.env['amis.sync.job'].sudo().search([
            ('picking_id', '=', self.id),
            ('direction', '=', direction),
            ('status', '=', 'pending'),
        ], limit=1)
        if existing:
            return

        vals = {
            'picking_id': self.id,
            'direction': direction,
            'status': 'pending',
        }
        # Gắn sale_order_id để hiển thị trên queue
        if direction == 'outgoing':
            so = self._get_related_sales_order()
            if so:
                vals['sale_order_id'] = so.id

        self.env['amis.sync.job'].sudo().create(vals)
        _logger.info('AMIS sync job enqueued for picking %s (%s)', self.name, direction)


    def action_test_outgoing_push(self):
        """Action de test manual push outgoing picking len MISA (chi dung khi da done)"""
        self.ensure_one()
        if self.state != 'done':
            raise UserError('Phiếu phải ở trạng thái "Hoàn thành" trước khi đẩy lên MISA.')
        self._enqueue_misa_sync('outgoing')
        return True

    def _sync_incoming_po_to_misa(self):
        self.ensure_one()
        if self.state != 'done' or self.picking_type_code != 'incoming':
            return

        if self.misa_inward_synced:
            _logger.info('Skip incoming sync for %s: already synced to MISA.', self.name)
            return

        purchase_order = self._get_related_purchase_order()
        if not purchase_order:
            return

        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        if not config.sync_incoming_po_enabled:
            return

        if not config.ensure_sync_ready():
            return

        voucher_payload, dictionary_items = self._prepare_misa_inward_payload(config, purchase_order)
        org_refid = voucher_payload.get('org_refid')

        # Nghiep vu hien tai uu tien map theo ma (code), tranh dung cac GUID tu sinh de khong lech du lieu MISA.
        # Neu danh muc da co san ben MISA, khong can goi save_dictionary.
        config.push_inward_voucher(voucher_payload, dictionary_items=[])

        self.sudo().write({
            'misa_inward_synced': True,
            'misa_inward_org_refid': org_refid or '',
        })

    def _get_related_purchase_order(self):
        self.ensure_one()
        po = self.move_ids_without_package.mapped('purchase_line_id.order_id')[:1]
        if po:
            return po
        if self.origin:
            return self.env['purchase.order'].sudo().search([('name', '=', self.origin)], limit=1)
        return self.env['purchase.order']

    def _sync_outgoing_so_to_misa(self):
        """Push SAVoucher (bán hàng kiêm xuất kho, voucher_type=13) lên MISA."""
        self.ensure_one()
        if self.state != 'done' or self.picking_type_code != 'outgoing':
            return

        sales_order = self._get_related_sales_order()
        if not sales_order:
            _logger.info('Skip outgoing sync for %s: không tìm được đơn bán hàng.', self.name)
            return

        # Chỉ sync đơn hàng có shopee_order_ref
        if not getattr(sales_order, 'shopee_order_ref', None):
            _logger.info('Skip outgoing sync for %s: đơn %s không có shopee_order_ref.', self.name, sales_order.name)
            return

        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        if not config.sync_outgoing_so_enabled:
            return

        if not config.ensure_sync_ready():
            return

        # Bỏ qua nếu đã sync SAVoucher
        if sales_order.misa_sa_voucher_synced:
            _logger.info('Skip outgoing sync for %s: đơn %s đã sync SAVoucher.', self.name, sales_order.name)
            return

        voucher_payload = self._prepare_misa_sa_voucher_payload(config, sales_order)
        org_refid = voucher_payload.get('org_refid', '')

        config.push_sa_voucher(voucher_payload)

        sales_order.sudo().write({
            'misa_sa_voucher_synced': True,
            'misa_sa_voucher_org_refid': org_refid,
        })
        _logger.info('SAVoucher synced for SO %s (picking %s), org_refid=%s', sales_order.name, self.name, org_refid)

    def _prepare_misa_sa_voucher_payload(self, config, sales_order):
        """Chuẩn bị payload SAVoucher (voucher_type=13) kèm in_outward (voucher_type=8)."""
        self.ensure_one()
        partner = self.partner_id or sales_order.partner_id

        branch_id = (config.misa_branch_id or '').strip()
        stock_id = (config.misa_stock_id or '').strip()

        if not branch_id:
            raise UserError('Thiếu MISA Branch ID trong cấu hình.')
        if not stock_id:
            raise UserError('Thiếu MISA Stock ID trong cấu hình.')

        # Auto-lookup account_object_id nếu chưa có trên partner
        account_object_id = (partner.misa_account_object_id or '').strip() if partner else ''
        account_object_code = (partner.ref or (partner.name if partner else '')) if partner else ''
        account_object_name = partner.display_name if partner else ''

        if not account_object_id and partner:
            account_object_id = self._misa_lookup_account_object(config, partner)
            if account_object_id:
                account_object_code = partner.ref or partner.name or ''
                account_object_name = partner.display_name or ''

        # Fallback: map theo shopee_shop_id.identifier (cứng)
        if not account_object_id:
            shop = getattr(sales_order, 'shopee_shop_id', None)
            shop_identifier = str(getattr(shop, 'identifier', '') or '').strip() if shop else ''
            if shop_identifier:
                misa_id, misa_code, misa_name = config.get_shopee_account_object_id(shop_identifier)
                if misa_id:
                    account_object_id = misa_id
                    account_object_code = misa_code or misa_name
                    account_object_name = misa_name

        # Fallback cuối: dùng config fallback (test)
        if not account_object_id:
            fallback_id = (config.misa_fallback_account_object_id or '').strip()
            if fallback_id:
                account_object_id = fallback_id
                account_object_code = (config.misa_fallback_account_object_code or '').strip()
                account_object_name = (config.misa_fallback_account_object_name or '').strip()
                _logger.warning('SAVoucher %s: dùng fallback account_object_id=%s', self.name, fallback_id)

        if not account_object_id:
            raise UserError(
                'Không tìm được MISA Account Object ID cho khách hàng: %s. '
                'Vui lòng điền MISA Account Object - Fallback (Test) trong cấu hình để test.' % (
                    partner.name if partner else '?'
                )
            )

        # Nếu code/name trống hoặc giống UUID → lookup MISA lấy tên thật rồi cache vào config
        import re
        _uuid_re = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)

        def _is_uuid(s):
            return bool(_uuid_re.match(s or ''))

        if not account_object_code or not account_object_name or _is_uuid(account_object_code) or _is_uuid(account_object_name):
            resolved = self._misa_lookup_account_object_by_id(config, account_object_id)
            if resolved:
                real_code = resolved.get('account_object_code') or ''
                real_name = resolved.get('account_object_name') or ''
                if real_code and not _is_uuid(real_code):
                    account_object_code = real_code
                if real_name and not _is_uuid(real_name):
                    account_object_name = real_name
                # Ghi cache vào config fallback để lần sau không cần lookup nữa
                fb_id = (config.misa_fallback_account_object_id or '').strip()
                if fb_id == account_object_id:
                    update = {}
                    if real_code and not _is_uuid(real_code) and _is_uuid(config.misa_fallback_account_object_code or ''):
                        update['misa_fallback_account_object_code'] = real_code
                    if real_name and not _is_uuid(real_name) and _is_uuid(config.misa_fallback_account_object_name or ''):
                        update['misa_fallback_account_object_name'] = real_name
                    if update:
                        config.sudo().write(update)
                _logger.info('SAVoucher: resolved account_object name=%s code=%s', account_object_name, account_object_code)
            else:
                _logger.warning('SAVoucher: không resolve được tên MISA cho account_object_id=%s, dùng tên partner', account_object_id)
                if not account_object_name or _is_uuid(account_object_name):
                    account_object_name = partner.display_name if partner else account_object_id
                if not account_object_code or _is_uuid(account_object_code):
                    account_object_code = partner.ref or (partner.name if partner else account_object_id)

        # Dùng org_refid từ SO nếu đã có (idempotent), hoặc sinh mới
        sa_voucher_refid = (sales_order.misa_sa_voucher_org_refid or '').strip()
        if not sa_voucher_refid:
            sa_voucher_refid = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'sa_voucher|%d' % self.id))

        outward_refid = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'outward|%d' % self.id))

        detail = []
        total_sale = 0.0
        total_vat = 0.0

        for idx, move in enumerate(
            self.move_ids_without_package.filtered(lambda m: m.quantity > 0), start=1
        ):
            product = move.product_id
            qty_done = float(move.quantity)

            sale_line = move.sale_line_id
            price_unit = float(sale_line.price_unit) if sale_line else 0.0
            discount = float(sale_line.discount) if sale_line and sale_line.discount else 0.0
            amount_oc = qty_done * price_unit * (1.0 - discount / 100.0)

            vat_rate = 0.0
            if sale_line:
                for tax in sale_line.tax_id:
                    if tax.amount_type == 'percent':
                        vat_rate = float(tax.amount)
                        break
            vat_amount = amount_oc * vat_rate / 100.0
            total_sale += amount_oc
            total_vat += vat_amount

            inventory_item_id = (product.misa_inventory_item_id or '').strip()
            unit_id = (move.product_uom.misa_unit_id or '').strip()
            if not inventory_item_id and product.default_code:
                inventory_item_id, fetched_unit_id = self._misa_lookup_inventory_item(config, product, move.product_uom)
                if not unit_id and fetched_unit_id:
                    unit_id = fetched_unit_id
            if not unit_id:
                unit_id = self._misa_lookup_unit(config, move.product_uom)

            ref_detail_id = (move.misa_ref_detail_id or '').strip()
            if not ref_detail_id:
                ref_detail_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'sa_v_detail|%d|%d' % (self.id, move.id)))
                move.sudo().write({'misa_ref_detail_id': ref_detail_id})

            detail.append({
                'ref_detail_id': ref_detail_id,
                'refid': sa_voucher_refid,
                'inventory_item_id': inventory_item_id,
                'unit_id': unit_id,
                'main_unit_id': unit_id,
                'stock_id': stock_id,
                'account_object_id': account_object_id,
                'sort_order': idx,
                'is_promotion': False,
                'un_resonable_cost': False,
                'not_in_vat_declaration': False,
                'quantity': qty_done,
                'unit_price': price_unit,
                'unit_price_after_tax': 0.0,
                'unit_price_after_discount': price_unit * (1.0 - discount / 100.0),
                'amount_oc': amount_oc,
                'amount': amount_oc,
                'discount_rate': discount,
                'discount_amount_oc': qty_done * price_unit * discount / 100.0,
                'discount_amount': qty_done * price_unit * discount / 100.0,
                'vat_rate': vat_rate,
                'vat_amount_oc': vat_amount,
                'vat_amount': vat_amount,
                'main_convert_rate': 1.0,
                'main_quantity': qty_done,
                'amount_after_tax': 0.0,
                'invoiced_quantity': qty_done,
                'main_invoiced_quantity': 0.0,
                'export_tax_rate': 0.0,
                'export_tax_amount': 0.0,
                'description': product.display_name,
                'debit_account': '131',
                'credit_account': '5111',
                'vat_account': '3331',
                'exchange_rate_operator': '*',
                'vat_description': 'Thue GTGT - %s' % product.display_name,
                'account_object_name': account_object_name,
                'account_object_code': account_object_code,
                'account_object_address': partner.contact_address_complete if partner else '',
                'inventory_item_code': product.default_code or str(product.id),
                'inventory_item_type': 0,
                'unit_name': move.product_uom.name,
                'main_unit_name': move.product_uom.name,
                'stock_code': 'HLV',
                'stock_name': 'HLV',
                'inventory_item_name': product.display_name,
                'is_follow_serial_number': False,
                'is_allow_duplicate_serial_number': False,
                'is_unit_price_after_tax': False,
                'is_description': False,
                'is_description_import': False,
                'discount_type': 0,
                'exported_invoice_at_least_one': False,
                'inventory_resale_type_id': 0,
                'return_quantity': 0.0,
                'is_un_update_outward_price': False,
                'state': 0,
            })

        total_amount = total_sale + total_vat
        refdate = self._to_misa_date(self.date_done)
        shopee_ref = getattr(sales_order, 'shopee_order_ref', '') or ''

        in_outward = {
            'voucher_type': 8,
            'is_get_new_id': True,
            'is_allow_group': False,
            'org_reftype': 0,
            'act_voucher_type': 0,
            'total_amount': 0,
            'refid': outward_refid,
            'account_object_id': account_object_id,
            'branch_id': branch_id,
            'display_on_book': 0,
            'reforder': int(datetime.utcnow().timestamp() * 1000),
            'refdate': refdate,
            'posted_date': refdate,
            'is_posted_finance': False,
            'is_posted_management': False,
            'is_posted_inventory_book_finance': False,
            'is_posted_inventory_book_management': False,
            'is_branch_issued': False,
            'is_sale_with_outward': True,
            'is_invoice_replace': False,
            'total_amount_finance': 0,
            'total_amount_management': 0,
            'refno_finance': '',
            'refno_management': '',
            'account_object_name': account_object_name,
            'account_object_code': account_object_code,
            'account_object_address': partner.contact_address_complete if partner else '',
            'journal_memo': 'Xuat kho ban hang %s (Odoo: %s)' % (sales_order.name, self.name),
            'reftype': 2020,
            'is_executed': False,
            'publish_status': 0,
            'is_invoice_deleted': False,
            'invoice_status': 0,
            'is_invoice_receipted': False,
            'is_reject_handler': False,
            'auto_refno': False,
            'state': 0,
        }

        voucher = {
            'voucher_type': 13,
            'is_get_new_id': True,
            'org_refid': sa_voucher_refid,
            'is_allow_group': False,
            'org_refno': sales_order.name,
            'org_reftype': 3530,
            'org_reftype_name': 'Ban hang',
            'refno': '',
            'act_voucher_type': 0,
            'refid': sa_voucher_refid,
            'branch_id': branch_id,
            'account_object_id': account_object_id,
            'display_on_book': 0,
            'outward_exported_status': 1,
            'debt_status': 0,
            'reforder': int(datetime.utcnow().timestamp() * 1000),
            'discount_rate_voucher': 0.0,
            'refdate': refdate,
            'posted_date': refdate,
            'inv_date': refdate,
            'is_posted_finance': False,
            'is_posted_management': False,
            'include_invoice': 0,
            'include_invoice_import': False,
            'is_invoice_exported': False,
            'is_paid': False,
            'is_sale_with_outward': True,
            'is_invoice_exported_last_year': False,
            'exchange_rate': 1.0,
            'total_sale_amount_oc': total_sale,
            'total_sale_amount': total_sale,
            'total_amount_oc': total_amount,
            'total_amount': total_amount,
            'total_discount_amount_oc': 0.0,
            'total_discount_amount': 0.0,
            'total_vat_amount_oc': total_vat,
            'total_vat_amount': total_vat,
            'total_export_tax_amount': 0.0,
            'refno_finance': '',
            'refno_management': '',
            'account_object_name': account_object_name,
            'account_object_code': account_object_code,
            'account_object_address': partner.contact_address_complete if partner else '',
            'account_object_tax_code': (partner.vat or '') if partner else '',
            'journal_memo': 'Ban hang %s (Shopee: %s) (Odoo: %s)' % (sales_order.name, shopee_ref, self.name),
            'currency_id': sales_order.currency_id.name or 'VND',
            'discount_type': 0,
            'paid_type': 0,
            'publish_status': 0,
            'send_email_status': 0,
            'is_remind_debt': True,
            'is_un_limit': False,
            'outward_refid': outward_refid,
            'reftype': 3530,
            'auto_refno': False,
            'state': 0,
            'detail': detail,
            'in_outward': in_outward,
        }
        return voucher

    def _get_related_sales_order(self):
        self.ensure_one()
        # Tim SO tu sale_line_id (Many2one tren stock.move)
        so = self.move_ids_without_package.mapped('sale_line_id.order_id')[:1]
        if so:
            return so
        # Tim theo origin (ten SO)
        if self.origin:
            return self.env['sale.order'].sudo().search([('name', '=', self.origin)], limit=1)
        return self.env['sale.order']

    def _to_misa_date(self, value):
        if not value:
            value = datetime.utcnow()
        if hasattr(value, 'strftime'):
            return value.strftime('%Y-%m-%d')
        return str(value)[:10]

    def _prepare_misa_inward_payload(self, config, purchase_order):
        self.ensure_one()
        partner = self.partner_id or purchase_order.partner_id

        refid = (self.misa_inward_org_refid or '').strip()
        if not refid:
            raise UserError('Thiếu MISA org_refid phiếu nhập. Vui lòng điền trường "MISA org_refid phiếu nhập" trên phiếu nhập trước khi đồng bộ.')

        branch_id = (config.misa_branch_id or '').strip()
        stock_id = (config.misa_stock_id or '').strip()

        # Auto-lookup account_object_id nếu chưa có trên partner
        account_object_id = (partner.misa_account_object_id or '').strip() if partner else ''
        if not account_object_id and partner:
            account_object_id = self._misa_lookup_account_object(config, partner)

        missing_header = []
        if not branch_id:
            missing_header.append('MISA Branch ID (cấu hình)')
        if not stock_id:
            missing_header.append('MISA Stock ID (cấu hình)')
        if not account_object_id:
            missing_header.append('MISA Account Object ID (nhà cung cấp: %s)' % (partner.name if partner else '?'))
        if missing_header:
            raise UserError('Thiếu mapping ID MISA ở phần đầu chứng từ: %s' % ', '.join(missing_header))

        # Kho MISA co dinh: HLV
        misa_warehouse_code = 'HLV'

        detail = []
        total_amount = 0.0

        for idx, move in enumerate(self.move_ids_without_package.filtered(lambda m: m.quantity > 0), start=1):
            product = move.product_id
            qty_done = float(move.quantity)
            price_unit = float(move.purchase_line_id.price_unit if move.purchase_line_id else 0.0)
            amount = qty_done * price_unit
            total_amount += amount

            inventory_item_id = (product.misa_inventory_item_id or '').strip()
            unit_id = (move.product_uom.misa_unit_id or '').strip()

            # Auto-lookup nếu thiếu
            if not inventory_item_id and product.default_code:
                inventory_item_id, fetched_unit_id = self._misa_lookup_inventory_item(
                    config, product, move.product_uom
                )
                if not unit_id and fetched_unit_id:
                    unit_id = fetched_unit_id
            if not unit_id:
                unit_id = self._misa_lookup_unit(config, move.product_uom)

            ref_detail_id = (move.misa_ref_detail_id or '').strip()
            if not ref_detail_id:
                # Sinh ref_detail_id dạng stable UUID từ picking+move để idempotent
                ref_detail_id = str(uuid.uuid5(
                    uuid.NAMESPACE_DNS,
                    'ref_detail|%s|%d' % (self.name, move.id)
                ))
                move.sudo().write({'misa_ref_detail_id': ref_detail_id})

            missing_line = []
            if not inventory_item_id:
                missing_line.append('MISA Inventory Item ID (product: %s)' % (product.default_code or product.name))
            if not unit_id:
                missing_line.append('MISA Unit ID (uom: %s)' % move.product_uom.name)
            if missing_line:
                raise UserError(
                    'Thiếu mapping ID MISA ở dòng hàng %s (%s): %s' % (
                        move.display_name,
                        product.display_name,
                        ', '.join(missing_line),
                    )
                )

            # Tai khoan co dinh theo yeu cau: Kho 1561, Cong no 331
            debit_account = '1561'
            credit_account = '331'

            detail.append({
                'ref_detail_id': ref_detail_id,
                'refid': refid,
                'inventory_item_id': inventory_item_id,
                'stock_id': stock_id,
                'unit_id': unit_id,
                'main_unit_id': unit_id,
                'account_object_id': account_object_id,
                'sort_order': idx,
                'inventory_resale_type_id': 0,
                'un_resonable_cost': False,
                'is_promotion': False,
                'quantity': qty_done,
                'unit_price_finance': price_unit,
                'amount_finance': amount,
                'unit_price_management': price_unit,
                'amount_management': amount,
                'main_unit_price_finance': price_unit,
                'main_unit_price_management': price_unit,
                'main_convert_rate': 1.0,
                'main_quantity': qty_done,
                'amount_finance_oc': amount,
                'amount_management_oc': amount,
                'description': product.display_name,
                'debit_account': debit_account,
                'credit_account': credit_account,
                'exchange_rate_operator': '*',
                'account_object_name': partner.display_name if partner else '',
                'account_object_code': partner.ref or (partner.name if partner else ''),
                'inventory_item_code': product.default_code or str(product.id),
                'inventory_item_type': 0,
                'unit_name': move.product_uom.name,
                'stock_code': misa_warehouse_code,
                'main_unit_name': move.product_uom.name,
                'inventory_item_name': product.display_name,
                'stock_name': misa_warehouse_code,
                'account_name': debit_account,
                'is_follow_serial_number': False,
                'is_allow_duplicate_serial_number': False,
                'is_description': False,
                'is_description_import': False,
                'is_promotion_import': False,
                'un_resonable_cost_import': False,
                'state': 0,
            })

        voucher = {
            'voucher_type': 7,
            'is_get_new_id': True,
            'org_refid': refid,
            'is_allow_group': False,
            'org_refno': self.name,
            'org_reftype': 2014,
            'org_reftype_name': 'Phieu nhap kho',
            'refid': refid,
            'act_voucher_type': 0,
            'reftype': 2014,
            'reftype_name': 'Nhap kho',
            'branch_id': branch_id,
            'account_object_id': account_object_id,
            'display_on_book': 0,
            'unit_price_method': 0,
            'reforder': int(datetime.utcnow().timestamp() * 1000),
            'refdate': self._to_misa_date(self.date_done),
            'posted_date': self._to_misa_date(self.date_done),
            'is_posted_finance': False,
            'is_posted_management': False,
            'is_posted_inventory_book_finance': False,
            'is_posted_inventory_book_management': False,
            'is_return_with_inward': False,
            'is_created_sa_return_last_year': False,
            'total_amount': total_amount,
            'total_amount_finance': total_amount,
            'total_amount_management': total_amount,
            'exchange_rate': 1.0,
            'refno_finance': '',
            'refno_management': '',
            'account_object_name': partner.display_name if partner else '',
            'account_object_address': partner.contact_address_complete if partner else '',
            'journal_memo': 'Nhap kho tu don mua %s (Odoo: %s)' % (purchase_order.name, self.name),
            'currency_id': (purchase_order.currency_id.name or 'VND'),
            'account_object_code': partner.ref or (partner.name if partner else ''),
            'is_executed': False,
            'is_adjust_value': False,
            'state': 0,
            'detail': detail,
        }
        return voucher, []

    # ── Auto-lookup helpers ────────────────────────────────────────────────────

    def _misa_lookup_account_object_by_id(self, config, account_object_id):
        """Tìm item account_object trong MISA dictionary theo ID (UUID).
        Trả về dict item hoặc None. Dùng cached list (không call API thêm)."""
        if not account_object_id:
            return None
        uid_lower = account_object_id.lower()
        for a in config._get_all_dictionary(1):
            if (a.get('account_object_id') or '').lower() == uid_lower:
                return a
        return None

    def _misa_lookup_account_object(self, config, partner):
        """Tìm account_object_id MISA theo tên partner, lưu vào partner."""
        if not partner:
            return ''
        search_name = (partner.name or '').upper()
        for a in config._get_all_dictionary(1):
            aname = (a.get('account_object_name') or '').upper()
            acode = (a.get('account_object_code') or '').upper()
            if search_name and (search_name in aname or search_name in acode):
                misa_id = a.get('account_object_id') or ''
                if misa_id:
                    partner.sudo().write({'misa_account_object_id': misa_id})
                    _logger.info('Auto-mapped partner %s → account_object_id=%s', partner.name, misa_id)
                return misa_id
        _logger.warning('MISA account_object not found for partner: %s', partner.name)
        return ''

    def _misa_lookup_inventory_item(self, config, product, uom):
        """Tìm inventory_item_id MISA theo default_code, lưu vào product + uom."""
        code = (product.default_code or '').strip()
        if not code:
            return '', ''
        for p in config._get_all_dictionary(2):
            if (p.get('inventory_item_code') or '').strip() == code:
                item_id = p.get('inventory_item_id') or ''
                unit_id = p.get('unit_id') or ''
                if item_id:
                    product.sudo().write({'misa_inventory_item_id': item_id})
                    _logger.info('Auto-mapped product %s → inventory_item_id=%s', code, item_id)
                if unit_id and uom and not uom.misa_unit_id:
                    uom.sudo().write({'misa_unit_id': unit_id})
                    _logger.info('Auto-mapped uom %s → unit_id=%s', uom.name, unit_id)
                return item_id, unit_id
        _logger.warning('MISA inventory_item not found for product code: %s', code)
        return '', ''

    def _misa_lookup_unit(self, config, uom):
        """Tìm unit_id MISA theo tên uom, lưu vào uom."""
        if not uom:
            return ''
        name = (uom.name or '').strip()
        for u in config._get_all_dictionary(4):
            if (u.get('unit_name') or '').strip() == name:
                unit_id = u.get('unit_id') or ''
                if unit_id:
                    uom.sudo().write({'misa_unit_id': unit_id})
                    _logger.info('Auto-mapped uom %s → unit_id=%s', name, unit_id)
                return unit_id
        _logger.warning('MISA unit not found for uom: %s', name)
        return ''


class ResPartnerAmisMapping(models.Model):
    _inherit = 'res.partner'

    misa_account_object_id = fields.Char(
        string='MISA Account Object ID',
        help='ID thật của đối tượng (nhà cung cấp/khách hàng) trên MISA.',
    )


class ProductProductAmisMapping(models.Model):
    _inherit = 'product.product'

    misa_inventory_item_id = fields.Char(
        string='MISA Inventory Item ID',
        help='ID thật của vật tư/hàng hóa trên MISA.',
    )


class UomUomAmisMapping(models.Model):
    _inherit = 'uom.uom'

    misa_unit_id = fields.Char(
        string='MISA Unit ID',
        help='ID thật của đơn vị tính trên MISA.',
    )


class StockMoveAmisMapping(models.Model):
    _inherit = 'stock.move'

    misa_ref_detail_id = fields.Char(
        string='MISA Ref Detail ID',
        help='ID thật của dòng chi tiết chứng từ trên MISA.',
    )
