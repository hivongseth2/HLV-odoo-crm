# -*- coding: utf-8 -*-
import logging
import threading
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
                if picking.picking_type_code == 'incoming':
                    picking._sync_misa_async('incoming')
                elif picking.picking_type_code == 'outgoing':
                    picking._sync_misa_async('outgoing')
            except Exception:
                _logger.exception('AMIS sync failed for picking %s', picking.name)
        return res

    def _sync_misa_async(self, direction):
        """Chạy sync MISA trong thread riêng để không block UI."""
        self.ensure_one()
        picking_id = self.id
        dbname = self.env.cr.dbname
        uid = self.env.uid
        context = dict(self.env.context)

        def _run():
            import odoo
            with odoo.registry(dbname).cursor() as cr:
                new_env = odoo.api.Environment(cr, uid, context)
                pick = new_env['stock.picking'].browse(picking_id)
                try:
                    if direction == 'incoming':
                        pick._sync_incoming_po_to_misa()
                    else:
                        pick._sync_outgoing_so_to_misa()
                    cr.commit()
                except Exception:
                    cr.rollback()
                    _logger.exception('AMIS async sync failed for picking id=%s', picking_id)

        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def action_test_outgoing_push(self):
        """Action de test manual push outgoing picking len MISA (chi dung khi da done)"""
        self.ensure_one()
        if self.state != 'done':
            raise UserError('Phiếu phải ở trạng thái "Hoàn thành" trước khi đẩy lên MISA.')
        
        self._sync_outgoing_so_to_misa()
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

    def _stable_uuid(self, *parts):
        base = '|'.join(str(p or '') for p in parts)
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, base))

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
        account_object_id = (partner.misa_account_object_id or '').strip() if partner else ''

        missing_header = []
        if not branch_id:
            missing_header.append('MISA Branch ID (cấu hình)')
        if not stock_id:
            missing_header.append('MISA Stock ID (cấu hình)')
        if not account_object_id:
            missing_header.append('MISA Account Object ID (nhà cung cấp)')
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
            ref_detail_id = (move.misa_ref_detail_id or '').strip()

            missing_line = []
            if not ref_detail_id:
                missing_line.append('MISA Ref Detail ID')
            if not inventory_item_id:
                missing_line.append('MISA Inventory Item ID')
            if not unit_id:
                missing_line.append('MISA Unit ID')
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
