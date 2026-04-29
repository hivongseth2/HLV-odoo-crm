# -*- coding: utf-8 -*-
import logging
import uuid
from datetime import datetime

from odoo import models

_logger = logging.getLogger(__name__)

ZERO_UUID = '00000000-0000-0000-0000-000000000000'


class StockPickingAmisSync(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        res = super().button_validate()
        for picking in self:
            try:
                picking._sync_incoming_po_to_misa()
            except Exception:
                _logger.exception('AMIS sync failed for picking %s', picking.name)
        return res

    def _sync_incoming_po_to_misa(self):
        self.ensure_one()
        if self.state != 'done' or self.picking_type_code != 'incoming':
            return

        purchase_order = self._get_related_purchase_order()
        if not purchase_order:
            return

        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        if not config.ensure_sync_ready():
            return

        voucher_payload, dictionary_items = self._prepare_misa_inward_payload(config, purchase_order)

        # Theo tai lieu ACT OpenAPI: dong bo danh muc truoc, sau do cất de nghi sinh chung tu.
        config.push_dictionary(dictionary_items)
        config.push_inward_voucher(voucher_payload, dictionary_items=dictionary_items)

    def _get_related_purchase_order(self):
        self.ensure_one()
        po = self.move_ids_without_package.mapped('purchase_line_id.order_id')[:1]
        if po:
            return po
        if self.origin:
            return self.env['purchase.order'].sudo().search([('name', '=', self.origin)], limit=1)
        return self.env['purchase.order']

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

        account_object_id = self._stable_uuid('partner', partner.id)
        branch_id = self._stable_uuid('company', self.company_id.id)
        refid = self._stable_uuid('picking', self.id)

        detail = []
        dictionary = []
        total_amount = 0.0

        for idx, move in enumerate(self.move_ids_without_package.filtered(lambda m: m.quantity > 0), start=1):
            product = move.product_id
            qty_done = float(move.quantity)
            price_unit = float(move.purchase_line_id.price_unit if move.purchase_line_id else 0.0)
            amount = qty_done * price_unit
            total_amount += amount

            inventory_item_id = self._stable_uuid('product', product.id)
            stock_id = self._stable_uuid('location', self.location_dest_id.id)
            unit_id = self._stable_uuid('uom', move.product_uom.id)

            debit_account = (product.categ_id.property_stock_valuation_account_id.code or '1561') if product.categ_id else '1561'
            credit_account = (partner.property_account_payable_id.code or '3311') if partner else '3311'

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
                'stock_code': self.location_dest_id.complete_name,
                'main_unit_name': move.product_uom.name,
                'inventory_item_name': product.display_name,
                'stock_name': self.location_dest_id.complete_name,
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
            'is_vendor': True,
            'is_customer': False,
            'is_employee': False,
            'inactive': False,
            'account_object_code': partner.ref or (partner.name if partner else ''),
            'account_object_name': partner.display_name if partner else '',
            'address': partner.contact_address_complete if partner else '',
            'country': partner.country_id.name if partner and partner.country_id else 'Viet Nam',
            'pay_account': '3311',
            'receive_account': '1311',
            'reftype': 0,
            'reftype_category': 0,
            'branch_id': branch_id,
            'state': 0,
        })
        dictionary.append({
            'dictionary_type': 5,
            'stock_id': self._stable_uuid('location', self.location_dest_id.id),
            'branch_id': branch_id,
            'inactive': False,
            'stock_code': self.location_dest_id.complete_name,
            'stock_name': self.location_dest_id.complete_name,
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
        return voucher, list(dedup.values())
