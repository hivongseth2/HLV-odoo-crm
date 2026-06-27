# -*- coding: utf-8 -*-
import json
import logging
import uuid

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

ZERO_UUID = '00000000-0000-0000-0000-000000000000'


class PurchaseOrderAmisSync(models.Model):
    _inherit = 'purchase.order'

    misa_purchase_order_synced = fields.Boolean(
        string='Da sync Don mua hang MISA',
        default=False,
        copy=False,
        help='Don mua hang (pu_order, voucher_type=21) da duoc day len MISA.',
    )
    misa_purchase_order_org_refid = fields.Char(
        string='MISA org_refid Don mua hang',
        copy=False,
        help='org_refid dung khi push Don mua hang len MISA.',
    )
    misa_purchase_order_refid = fields.Char(
        string='MISA refid Don mua hang',
        copy=False,
        help='refid thuc te cua Don mua hang sau khi MISA xu ly callback.',
    )

    def button_confirm(self):
        res = super().button_confirm()
        if self.env.context.get('skip_misa_purchase_order_sync'):
            return res
        for order in self:
            try:
                order._maybe_enqueue_misa_purchase_order()
            except Exception:
                _logger.exception('AMIS purchase order enqueue failed for PO %s', order.name)
        return res

    def action_sync_misa_purchase_order(self):
        for order in self:
            order._enqueue_misa_purchase_order(raise_on_skip=True)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Da enqueue',
                'message': 'Don mua hang se duoc dong bo len MISA trong vai giay.',
                'type': 'success',
                'sticky': False,
            },
        }

    def action_reset_misa_purchase_order(self):
        for order in self:
            order.sudo().write({
                'misa_purchase_order_synced': False,
                'misa_purchase_order_org_refid': False,
                'misa_purchase_order_refid': False,
            })
        return True

    def _maybe_enqueue_misa_purchase_order(self):
        self.ensure_one()
        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        if not config.sync_purchase_order_enabled:
            return
        if self._is_misa_imported_purchase_order():
            _logger.info('Skip MISA PO push for %s: looks imported from MISA.', self.name)
            return
        self._enqueue_misa_purchase_order(raise_on_skip=False)

    def _is_misa_imported_purchase_order(self):
        self.ensure_one()
        for field_name in ('x_studio_misa_date', 'x_studio_misa_purchase_status'):
            if field_name in self._fields and self[field_name]:
                return True
        return False

    def _enqueue_misa_purchase_order(self, raise_on_skip=False):
        self.ensure_one()
        if self.state not in ('purchase', 'done'):
            if raise_on_skip:
                raise UserError('Don mua hang "%s" phai o trang thai Da xac nhan hoac Hoan thanh.' % self.name)
            return
        if self.misa_purchase_order_synced:
            if raise_on_skip:
                raise UserError('Don mua hang "%s" da duoc sync len MISA roi.' % self.name)
            return

        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        if not config.sync_purchase_order_enabled:
            if raise_on_skip:
                raise UserError('Tinh nang dong bo Don mua hang MISA chua duoc bat trong cau hinh.')
            return

        existing = self.env['amis.sync.job'].sudo().search([
            ('purchase_order_id', '=', self.id),
            ('direction', '=', 'purchase_order'),
            ('status', '=', 'pending'),
        ], limit=1)
        if existing:
            if raise_on_skip:
                raise UserError('Don mua hang "%s" da co job dang cho xu ly.' % self.name)
            return

        self.env['amis.sync.job'].sudo().create({
            'purchase_order_id': self.id,
            'direction': 'purchase_order',
            'status': 'pending',
        })
        _logger.info('AMIS purchase order job enqueued for PO %s', self.name)

    def _sync_purchase_order_to_misa(self):
        self.ensure_one()
        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        if not config.sync_purchase_order_enabled:
            return
        config.ensure_sync_ready()

        if self.misa_purchase_order_synced:
            _logger.info('Skip MISA PO %s: already synced.', self.name)
            return

        voucher_payload = self._prepare_misa_purchase_order_payload(config)
        config.push_purchase_order(voucher_payload, dictionary_items=[])
        self.sudo().write({
            'misa_purchase_order_org_refid': voucher_payload.get('org_refid') or '',
        })

    def _prepare_misa_purchase_order_payload(self, config):
        self.ensure_one()
        partner = self.partner_id
        if not partner:
            raise UserError('Don mua hang "%s" thieu nha cung cap.' % self.name)

        lines = self.order_line.filtered(lambda l: not getattr(l, 'display_type', False) and l.product_qty > 0)
        if not lines:
            raise UserError('Don mua hang "%s" khong co dong hang hoa de sync MISA.' % self.name)

        missing_dictionary_items = []
        org_refid = (self.misa_purchase_order_org_refid or '').strip()
        if not org_refid:
            org_refid = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'misa_purchase_order|%d' % self.id))
            self.sudo().write({'misa_purchase_order_org_refid': org_refid})

        account_object = self._ensure_misa_account_object(config, partner, missing_dictionary_items)
        account_object_id = account_object.get('account_object_id') or ''
        account_object_code = account_object.get('account_object_code') or ''
        account_object_name = account_object.get('account_object_name') or ''
        refdate = self._misa_purchase_datetime(self.date_order or fields.Datetime.now())
        receive_date = self._misa_purchase_datetime(self.date_planned or self.date_order or fields.Datetime.now())
        branch_id = (config.misa_branch_id or '').strip() or ZERO_UUID
        now_ms = int(fields.Datetime.now().timestamp() * 1000)
        delivery_term = self._misa_field_value('x_studio_delivery_term')
        payment_term_text = self._misa_payment_term_text()
        receive_address = self._misa_receive_address()
        purchase_status = self._misa_field_value('x_studio_misa_purchase_status') or 'Chua thuc hien'
        employee_name = self.user_id.name if self.user_id else ''
        stock_code = self._misa_purchase_stock_code()

        detail = []
        total_sale_amount = 0.0
        total_discount_amount = 0.0
        total_vat_amount = 0.0
        total_amount = 0.0

        for idx, line in enumerate(lines, start=1):
            product = line.product_id
            qty = float(line.product_qty or 0.0)
            unit_price = float(line.price_unit or 0.0)
            discount_rate = float(getattr(line, 'discount', 0.0) or 0.0)
            amount = float(getattr(line, 'price_subtotal', qty * unit_price) or 0.0)
            tax_amount = float(getattr(line, 'price_tax', 0.0) or 0.0)
            total_line = float(getattr(line, 'price_total', amount + tax_amount) or 0.0)
            gross_amount = qty * unit_price
            discount_amount = max(gross_amount - amount, 0.0)
            vat_rate = self._misa_purchase_line_vat_rate(line)

            total_sale_amount += amount
            total_discount_amount += discount_amount
            total_vat_amount += tax_amount
            total_amount += total_line

            unit = self._ensure_misa_unit(config, line.product_uom, missing_dictionary_items)
            inventory_item = self._ensure_misa_inventory_item(
                config, product, line.product_uom, unit, unit_price, missing_dictionary_items
            )
            inventory_item_id = inventory_item.get('inventory_item_id') or ''
            inventory_item_code = inventory_item.get('inventory_item_code') or (product.default_code or str(product.id))
            inventory_item_name = inventory_item.get('inventory_item_name') or product.display_name
            unit_id = unit.get('unit_id') or ''
            unit_name = unit.get('unit_name') or line.product_uom.name
            ref_detail_id = (line.misa_purchase_order_ref_detail_id or '').strip()
            if not ref_detail_id:
                ref_detail_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'misa_purchase_order_detail|%d|%d' % (self.id, line.id)))
                line.sudo().write({'misa_purchase_order_ref_detail_id': ref_detail_id})

            detail.append({
                'ref_detail_id': ref_detail_id,
                'refid': org_refid,
                'sort_order': idx,
                'is_description': False,
                'inventory_item_id': inventory_item_id,
                'inventory_item_code': inventory_item_code,
                'inventory_item_name': inventory_item_name,
                'description': line.name or inventory_item_name,
                'unit_id': unit_id,
                'main_unit_id': unit_id,
                'unit_name': unit_name,
                'main_unit_name': unit_name,
                'main_convert_rate': 1.0,
                'quantity': qty,
                'main_quantity': qty,
                'quantity_receipt': 0.0,
                'quantity_receipt_last_year': 0.0,
                'unit_price': unit_price,
                'main_unit_price': unit_price,
                'unit_price_after_tax': 0.0,
                'amount_oc': amount,
                'amount': amount,
                'discount_rate': discount_rate,
                'discount_amount_oc': discount_amount,
                'discount_amount': discount_amount,
                'vat_rate': vat_rate,
                'vat_amount_oc': tax_amount,
                'vat_amount': tax_amount,
                'exchange_rate_operator': '*',
                'stock_code': 'HLV',
                'stock_name': 'HLV',
                'inventory_item_type': 0,
                'is_allow_duplicate_serial_number': False,
                'is_follow_serial_number': False,
                'is_description_import': False,
                'custom_field5': stock_code,
                'state': 0,
            })


        voucher = {
            'voucher_type': 21,
            'is_get_new_id': True,
            'org_refid': org_refid,
            'is_allow_group': False,
            'org_refno': self.name,
            'org_reftype': 301,
            'org_reftype_name': 'Don mua hang',
            'act_voucher_type': 0,
            'refid': org_refid,
            'branch_id': branch_id,
            'status': 0,
            'reforder': now_ms,
            'refdate': refdate,
            'receive_date': receive_date,
            'exchange_rate': float(getattr(self, 'currency_rate', 1.0) or 1.0),
            'total_sale_amount_oc': total_sale_amount,
            'total_sale_amount': total_sale_amount,
            'total_amount_oc': total_amount,
            'total_amount': total_amount,
            'total_discount_amount_oc': total_discount_amount,
            'total_discount_amount': total_discount_amount,
            'total_vat_amount_oc': total_vat_amount,
            'total_vat_amount': total_vat_amount,
            'discount_type': 0,
            'discount_rate_voucher': 0.0,
            'refno': self.name,
            'account_object_id': account_object_id,
            'account_object_name': account_object_name,
            'account_object_address': partner.contact_address_complete or '',
            'account_object_tax_code': partner.vat or '',
            'account_object_code': account_object_code,
            'employee_name': employee_name,
            'purchase_employee_name': employee_name,
            'custom_field1': payment_term_text,
            'custom_field2': delivery_term,
            'custom_field5': stock_code,
            'custom_field10': purchase_status,
            'receive_address': receive_address,
            'journal_memo': self.origin or '',
            'description': self.origin or '',
            'currency_id': self.currency_id.name or 'VND',
            'reftype': 301,
            'auto_refno': False,
            'state': 0,
            'detail': detail,
        }

        self._push_missing_misa_dictionary(config, missing_dictionary_items)
        return voucher

    def _misa_field_value(self, field_name):
        if field_name not in self._fields:
            return ''
        value = self[field_name]
        if not value:
            return ''
        if hasattr(value, 'display_name'):
            return value.display_name or value.name or ''
        return str(value).strip()

    def _misa_payment_term_text(self):
        value = self._misa_field_value('x_studio_iu_kin_thanh_ton')
        if value:
            return value
        if 'payment_term_id' in self._fields and self.payment_term_id:
            return self.payment_term_id.name or ''
        return ''

    def _misa_receive_address(self):
        value = self._misa_field_value('x_studio_ddgh')
        if value:
            return value
        dest = self.picking_type_id.default_location_dest_id if self.picking_type_id else False
        if dest:
            return dest.complete_name or dest.display_name or dest.name or ''
        return self.company_id.partner_id.contact_address_complete or ''

    def _misa_purchase_stock_code(self):
        explicit = self._misa_field_value('x_studio_misa_purchase_stock_code')
        if explicit:
            return self._normalize_misa_stock_code(explicit)
        receive_address = self._misa_receive_address()
        normalized_address = self._normalize_misa_stock_code(receive_address)
        if 'BENCAM' in normalized_address:
            return 'BENCAM'
        if 'BEN CAM' in receive_address.upper() or 'BẾN CAM' in receive_address.upper():
            return 'BENCAM'
        dest = self.picking_type_id.default_location_dest_id if self.picking_type_id else False
        complete = (dest.complete_name or dest.display_name or dest.name or '') if dest else ''
        normalized_dest = self._normalize_misa_stock_code(complete)
        if 'KBC' in normalized_dest or 'BENCAM' in normalized_dest:
            return 'BENCAM'
        warehouse = self.picking_type_id.warehouse_id if self.picking_type_id else False
        if warehouse and warehouse.code:
            return self._normalize_misa_stock_code(warehouse.code)
        return 'HLV'

    def _normalize_misa_stock_code(self, value):
        value = (value or '').strip().upper()
        replacements = {
            ' ': '',
            '-': '',
            '_': '',
            'Ế': 'E',
            'É': 'E',
            'È': 'E',
            'Ê': 'E',
            'Ắ': 'A',
            'Á': 'A',
            'À': 'A',
            'Â': 'A',
            'Ã': 'A',
            'Đ': 'D',
        }
        for src, dst in replacements.items():
            value = value.replace(src, dst)
        return value

    def _misa_purchase_line_vat_rate(self, line):
        taxes = line.taxes_id.filtered(lambda t: t.amount_type == 'percent')
        if taxes:
            return float(taxes[0].amount or 0.0)
        return 0.0

    def _push_missing_misa_dictionary(self, config, dictionary_items):
        if not dictionary_items:
            return
        config.push_dictionary(dictionary_items)
        _logger.info('Created %d MISA dictionary items before PO %s sync.', len(dictionary_items), self.name)

    def _ensure_misa_account_object(self, config, partner, dictionary_items):
        existing_id = (getattr(partner, 'misa_account_object_id', '') or '').strip()
        if existing_id:
            return {
                'account_object_id': existing_id,
                'account_object_code': partner.ref or partner.name or '',
                'account_object_name': partner.display_name or partner.name or '',
            }

        found = self._find_misa_account_object_by_code_or_name(config, partner.ref, partner.name or partner.display_name)
        if found:
            return self._normalize_misa_account_object(found, partner)

        misa_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'misa_account_object|%d' % partner.id))
        code = self._misa_required_code(partner.ref or '', fallback_prefix='NCC', fallback_id=partner.id)
        name = (partner.display_name or partner.name or code).strip()
        item = {
            'dictionary_type': 1,
            'account_object_id': misa_id,
            'account_object_code': code,
            'account_object_name': name,
            'account_object_address': partner.contact_address_complete or '',
            'company_tax_code': partner.vat or '',
            'tel': partner.phone or partner.mobile or '',
            'mobile': partner.mobile or partner.phone or '',
            'email_address': partner.email or '',
            'is_vendor': True,
            'is_customer': False,
            'inactive': False,
            'state': 1,
        }
        dictionary_items.append(item)
        partner.sudo().write({'misa_account_object_id': misa_id})
        _logger.info('Prepared MISA vendor dictionary item for %s (%s)', name, code)
        return {
            'account_object_id': misa_id,
            'account_object_code': code,
            'account_object_name': name,
        }

    def _ensure_misa_unit(self, config, uom, dictionary_items):
        existing_id = (getattr(uom, 'misa_unit_id', '') or '').strip() if uom else ''
        name = (uom.name or '').strip() if uom else ''
        if existing_id:
            return {'unit_id': existing_id, 'unit_name': name}

        for item in config._get_all_dictionary(4):
            if name and (item.get('unit_name') or '').strip().casefold() == name.casefold():
                unit_id = (item.get('unit_id') or '').strip()
                unit_name = (item.get('unit_name') or name).strip()
                if unit_id:
                    uom.sudo().write({'misa_unit_id': unit_id})
                    return {'unit_id': unit_id, 'unit_name': unit_name}

        unit_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'misa_unit|%s' % name.casefold()))
        item = {
            'dictionary_type': 6,
            'unit_id': unit_id,
            'unit_name': name,
            'inactive': False,
            'state': 1,
        }
        dictionary_items.append(item)
        if uom:
            uom.sudo().write({'misa_unit_id': unit_id})
        _logger.info('Prepared MISA unit dictionary item for %s', name)
        return {'unit_id': unit_id, 'unit_name': name}

    def _ensure_misa_inventory_item(self, config, product, uom, unit, unit_price, dictionary_items):
        existing_id = (getattr(product, 'misa_inventory_item_id', '') or '').strip()
        code = self._misa_required_code(product.default_code or '', fallback_prefix='VT', fallback_id=product.id)
        name = (product.display_name or product.name or code).strip()
        if existing_id:
            return {
                'inventory_item_id': existing_id,
                'inventory_item_code': product.default_code or code,
                'inventory_item_name': name,
            }

        for item in config._get_all_dictionary(2):
            if (item.get('inventory_item_code') or '').strip() == code:
                item_id = (item.get('inventory_item_id') or '').strip()
                unit_id = (item.get('unit_id') or '').strip()
                if item_id:
                    product.sudo().write({'misa_inventory_item_id': item_id})
                if unit_id and uom and not (getattr(uom, 'misa_unit_id', '') or '').strip():
                    uom.sudo().write({'misa_unit_id': unit_id})
                return {
                    'inventory_item_id': item_id,
                    'inventory_item_code': item.get('inventory_item_code') or code,
                    'inventory_item_name': item.get('inventory_item_name') or name,
                }

        item_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'misa_inventory_item|%d' % product.id))
        unit_id = unit.get('unit_id') or ''
        unit_name = unit.get('unit_name') or (uom.name if uom else '')
        item = {
            'dictionary_type': 3,
            'inventory_item_id': item_id,
            'inventory_item_code': code,
            'inventory_item_name': name,
            'inventory_item_type': 0,
            'unit_id': unit_id,
            'unit_name': unit_name,
            'main_unit_id': unit_id,
            'main_unit_name': unit_name,
            'unit_list': json.dumps([{
                'unit_id': unit_id,
                'unit_name': unit_name,
                'convert_rate': 1.0,
                'is_main_unit': True,
            }], ensure_ascii=False),
            'sale_price1': float(unit_price or 0.0),
            'purchase_price': float(unit_price or 0.0),
            'stock_id': (config.misa_stock_id or '').strip(),
            'stock_code': 'HLV',
            'inactive': False,
            'state': 1,
        }
        dictionary_items.append(item)
        product.sudo().write({'misa_inventory_item_id': item_id})
        _logger.info('Prepared MISA inventory dictionary item for %s (%s)', name, code)
        return {
            'inventory_item_id': item_id,
            'inventory_item_code': code,
            'inventory_item_name': name,
        }

    def _find_pending_dictionary_item(self, dictionary_items, id_field, id_value):
        id_value = (id_value or '').strip().lower()
        if not id_value:
            return None
        for item in dictionary_items:
            if (item.get(id_field) or '').strip().lower() == id_value:
                return item
        return None

    def _find_misa_unit_by_id(self, config, unit_id):
        unit_id = (unit_id or '').strip().lower()
        if not unit_id:
            return None
        for item in config._get_all_dictionary(4):
            if (item.get('unit_id') or '').strip().lower() == unit_id:
                return item
        return None

    def _find_misa_inventory_item_by_id(self, config, inventory_item_id):
        inventory_item_id = (inventory_item_id or '').strip().lower()
        if not inventory_item_id:
            return None
        for item in config._get_all_dictionary(2):
            if (item.get('inventory_item_id') or '').strip().lower() == inventory_item_id:
                return item
        return None

    def _find_misa_account_object_by_code_or_name(self, config, partner_ref, partner_name):
        partner_ref = (partner_ref or '').strip()
        partner_name = (partner_name or '').strip()
        partner_ref_upper = partner_ref.upper()
        partner_name_upper = partner_name.upper()
        for item in config._get_all_dictionary(1):
            code = (item.get('account_object_code') or '').strip()
            name = (item.get('account_object_name') or '').strip()
            if partner_ref_upper and partner_ref_upper == code.upper():
                return item
            if partner_name_upper and partner_name_upper == name.upper():
                return item
        for item in config._get_all_dictionary(1):
            code = (item.get('account_object_code') or '').strip()
            name = (item.get('account_object_name') or '').strip()
            haystack = '%s %s' % (code.upper(), name.upper())
            if partner_name_upper and partner_name_upper in haystack:
                return item
        return None

    def _find_misa_account_object_by_id(self, config, account_object_id):
        account_object_id = (account_object_id or '').strip().lower()
        if not account_object_id:
            return None
        for item in config._get_all_dictionary(1):
            if (item.get('account_object_id') or '').strip().lower() == account_object_id:
                return item
        return None

    def _normalize_misa_account_object(self, item, partner):
        misa_id = (item.get('account_object_id') or '').strip()
        code = (item.get('account_object_code') or partner.ref or partner.name or '').strip()
        name = (item.get('account_object_name') or partner.display_name or partner.name or '').strip()
        if misa_id and getattr(partner, 'misa_account_object_id', False) != misa_id:
            partner.sudo().write({'misa_account_object_id': misa_id})
            _logger.info('Auto-mapped PO vendor %s to MISA account_object_id=%s', partner.display_name, misa_id)
        return {
            'account_object_id': misa_id,
            'account_object_code': code,
            'account_object_name': name,
        }

    def _misa_required_code(self, value, fallback_prefix, fallback_id):
        value = (value or '').strip()
        if value:
            return value
        return '%s%05d' % (fallback_prefix, int(fallback_id or 0))

    def _misa_purchase_datetime(self, value):
        if not value:
            value = fields.Datetime.now()
        if isinstance(value, str):
            value = fields.Datetime.from_string(value)
        localized = fields.Datetime.context_timestamp(self, value)
        return localized.isoformat()

class PurchaseOrderLineAmisSync(models.Model):
    _inherit = 'purchase.order.line'

    misa_purchase_order_ref_detail_id = fields.Char(
        string='MISA ref_detail_id Don mua hang',
        copy=False,
        help='ref_detail_id thuc te cua dong Don mua hang tren MISA, dung de link phieu mua/nhap kho.',
    )
