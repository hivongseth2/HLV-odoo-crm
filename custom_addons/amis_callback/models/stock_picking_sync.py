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
        self.env['amis.sync.job'].sudo().create({
            'picking_id': self.id,
            'direction': direction,
            'status': 'pending',
        })
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
        self.ensure_one()
        if self.state != 'done' or self.picking_type_code != 'outgoing':
            return

        sales_order = self._get_related_sales_order()
        if not sales_order:
            return

        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        if not config.sync_outgoing_so_enabled:
            return False
        
        if not config.ensure_sync_ready():
            return

        voucher_payload, dictionary_items = self._prepare_misa_outgoing_payload(config, sales_order)

        # Theo tai lieu ACT OpenAPI: dong bo danh muc truoc, sau do cất de nghi sinh chung tu.
        config.push_dictionary(dictionary_items)
        config.push_outgoing_voucher(voucher_payload, dictionary_items=dictionary_items)

    def _get_related_sales_order(self):
        self.ensure_one()
        # Tim SO tu sale_line_ids (neu co)
        so = self.move_ids_without_package.mapped('sale_line_ids.order_id')[:1]
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

    def _misa_lookup_account_object(self, config, partner):
        """Tìm account_object_id MISA theo tên partner, lưu vào partner."""
        if not partner:
            return ''
        search_name = (partner.name or '').upper()
        skip = 0
        while True:
            r = config.get_dictionary(data_type=1, skip=skip, take=100)
            items = r.get('items') or []
            if not items:
                break
            for a in items:
                aname = (a.get('account_object_name') or '').upper()
                acode = (a.get('account_object_code') or '').upper()
                if search_name and (search_name in aname or search_name in acode):
                    misa_id = a.get('account_object_id') or ''
                    if misa_id:
                        partner.sudo().write({'misa_account_object_id': misa_id})
                        _logger.info('Auto-mapped partner %s → account_object_id=%s', partner.name, misa_id)
                    return misa_id
            if len(items) < 100:
                break
            skip += 100
        _logger.warning('MISA account_object not found for partner: %s', partner.name)
        return ''

    def _misa_lookup_inventory_item(self, config, product, uom):
        """Tìm inventory_item_id MISA theo default_code, lưu vào product + uom."""
        code = (product.default_code or '').strip()
        if not code:
            return '', ''
        skip = 0
        while True:
            r = config.get_dictionary(data_type=2, skip=skip, take=100)
            items = r.get('items') or []
            if not items:
                break
            for p in items:
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
            if len(items) < 100:
                break
            skip += 100
        _logger.warning('MISA inventory_item not found for product code: %s', code)
        return '', ''

    def _misa_lookup_unit(self, config, uom):
        """Tìm unit_id MISA theo tên uom, lưu vào uom."""
        if not uom:
            return ''
        name = (uom.name or '').strip()
        r = config.get_dictionary(data_type=4, take=100)
        for u in (r.get('items') or []):
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

    def _prepare_misa_outgoing_payload(self, config, sales_order):
        """Chuan bi payload de dua phieu xuat kho len MISA.
        
        Tuong tu nhu nhap kho, nhung dung cho outgoing picking (xuat kho).
        Voucher_type dung la 8 (xuat kho) thay vi 7 (nhap kho).
        """
        self.ensure_one()
        partner = self.partner_id or sales_order.partner_id

        account_object_id = self._stable_uuid('partner', partner.id)
        branch_id = self._stable_uuid('company', self.company_id.id)
        refid = self._stable_uuid('picking', self.id)
        
        # Kho MISA co dinh: HLV
        misa_warehouse_code = 'HLV'
        stock_id = self._stable_uuid('warehouse_hlv', 'hlv')

        detail = []
        dictionary = []
        total_amount = 0.0

        for idx, move in enumerate(self.move_ids_without_package.filtered(lambda m: m.quantity > 0), start=1):
            product = move.product_id
            qty_done = float(move.quantity)
            price_unit = float(move.sale_line_id.price_unit if move.sale_line_id else 0.0)
            amount = qty_done * price_unit
            total_amount += amount

            # Map product theo default_code MISA -> Odoo
            inventory_item_id = self._stable_uuid('product', product.default_code or product.id)
            unit_id = self._stable_uuid('uom', move.product_uom.id)

            # Tai khoan co dinh theo yeu cau: Kho 1561, Cong no 331
            debit_account = '1561'
            credit_account = '331'

            detail.append({
                'ref_detail_id': self._stable_uuid('move', move.id),
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

            dictionary.append({
                'dictionary_type': 3,
                'inventory_item_id': inventory_item_id,
                'inventory_item_name': product.display_name,
                'inventory_item_code': product.default_code or str(product.id),
                'inventory_item_type': 0,
                'unit_id': unit_id,
                'inactive': False,
                'inventory_account': debit_account,
                'cogs_account': '632',
                'sale_account': '5111',
                'reftype': 0,
                'reftype_category': 0,
                'state': 0,
            })
            dictionary.append({
                'dictionary_type': 6,
                'unit_id': unit_id,
                'unit_name': move.product_uom.name,
                'inactive': False,
                'reftype_category': 0,
                'state': 0,
            })

        dictionary.append({
            'dictionary_type': 1,
            'account_object_id': account_object_id,
            'account_object_type': 0,
            'is_vendor': False,
            'is_customer': True,
            'is_employee': False,
            'inactive': False,
            'account_object_code': partner.ref or (partner.name if partner else ''),
            'account_object_name': partner.display_name if partner else '',
            'address': partner.contact_address_complete if partner else '',
            'country': partner.country_id.name if partner and partner.country_id else 'Viet Nam',
            'pay_account': '3111',
            'receive_account': '1111',
            'reftype': 0,
            'reftype_category': 0,
            'branch_id': branch_id,
            'state': 0,
        })
        dictionary.append({
            'dictionary_type': 5,
            'stock_id': stock_id,
            'branch_id': branch_id,
            'inactive': False,
            'stock_code': misa_warehouse_code,
            'stock_name': misa_warehouse_code,
            'reftype': 0,
            'reftype_category': 0,
            'state': 0,
        })

        # Khử trùng lặp theo (dictionary_type, id chính) để payload gọn và đúng giới hạn tài liệu.
        dedup = {}
        for item in dictionary:
            key_field = {
                1: 'account_object_id',
                3: 'inventory_item_id',
                5: 'stock_id',
                6: 'unit_id',
            }.get(item.get('dictionary_type'))
            key = (item.get('dictionary_type'), item.get(key_field))
            dedup[key] = item

        voucher = {
            'voucher_type': 8,
            'is_get_new_id': True,
            'org_refid': refid,
            'is_allow_group': False,
            'org_refno': self.name,
            'org_reftype': 2015,
            'org_reftype_name': 'Phieu xuat kho',
            'refid': refid,
            'act_voucher_type': 0,
            'reftype': 2015,
            'reftype_name': 'Xuat kho',
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
            'journal_memo': 'Xuat kho tu don hang %s (Odoo: %s)' % (sales_order.name, self.name),
            'currency_id': (sales_order.currency_id.name or 'VND'),
            'account_object_code': partner.ref or (partner.name if partner else ''),
            'is_executed': False,
            'is_adjust_value': False,
            'state': 0,
            'detail': detail,
        }
        return voucher, list(dedup.values())
