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
            order._enqueue_misa_purchase_order(raise_on_skip=True, force=True)
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
            order.order_line.sudo().write({
                'misa_purchase_order_org_ref_detail_id': False,
                'misa_purchase_order_ref_detail_id': False,
                'misa_purchase_order_ref_detail_synced': False,
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
        if (self.misa_purchase_order_org_refid or self.misa_purchase_order_refid):
            return False
        for field_name in ('x_studio_misa_date', 'x_studio_misa_purchase_status'):
            if field_name in self._fields and self[field_name]:
                return True
        return False

    def _enqueue_misa_purchase_order(self, raise_on_skip=False, force=False):
        self.ensure_one()
        if self.state not in ('purchase', 'done'):
            if raise_on_skip:
                raise UserError('Don mua hang "%s" phai o trang thai Da xac nhan hoac Hoan thanh.' % self.name)
            return
        if self.misa_purchase_order_synced and not force:
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

        voucher_payload = self._prepare_misa_purchase_order_payload(config)
        _logger.info(
            'Push MISA PO %s: status=%s, received=%s',
            self.name,
            voucher_payload.get('status'),
            ', '.join(
                '%s:%s/%s unit=%s main=%s rate=%s' % (
                    detail.get('inventory_item_code') or detail.get('inventory_item_name') or '',
                    detail.get('quantity_receipt') or 0.0,
                    detail.get('quantity') or 0.0,
                    detail.get('unit_id') or '',
                    detail.get('main_unit_id') or '',
                    detail.get('main_convert_rate') or 0.0,
                )
                for detail in voucher_payload.get('detail') or []
            ),
        )
        config.push_purchase_order(voucher_payload, dictionary_items=[])
        org_refid = voucher_payload.get('org_refid') or ''
        self.sudo().write({
            'misa_purchase_order_org_refid': org_refid,
            'misa_purchase_order_refid': org_refid,
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
        purchase_status_code = self._misa_purchase_status_code(lines)
        purchase_status = self._misa_purchase_status_name(purchase_status_code)
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
            quantity_receipt = self._misa_purchase_line_received_quantity(line)

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
            unit_values = self._misa_document_unit_values(
                config, inventory_item, line.product_uom, unit, qty, unit_price
            )
            ref_detail_id = (line.misa_purchase_order_org_ref_detail_id or '').strip()
            if not ref_detail_id:
                ref_detail_id = self._misa_purchase_order_line_org_ref_detail_id(line)
                line.sudo().write({'misa_purchase_order_org_ref_detail_id': ref_detail_id})

            detail.append({
                'ref_detail_id': ref_detail_id,
                'refid': org_refid,
                'sort_order': idx,
                'is_description': False,
                'inventory_item_id': inventory_item_id,
                'inventory_item_code': inventory_item_code,
                'inventory_item_name': inventory_item_name,
                'description': line.name or inventory_item_name,
                'unit_id': unit_values['unit_id'],
                'main_unit_id': unit_values['main_unit_id'],
                'unit_name': unit_values['unit_name'],
                'main_unit_name': unit_values['main_unit_name'],
                'main_convert_rate': unit_values['main_convert_rate'],
                'quantity': qty,
                'main_quantity': unit_values['main_quantity'],
                'quantity_receipt': quantity_receipt,
                # 'main_quantity_receipt': self._misa_convert_quantity(
                #     quantity_receipt,
                #     unit_values['main_convert_rate'],
                #     unit_values['exchange_rate_operator'],
                # ),
                # 'quantity_receipt_last_year': 0.0,
                'unit_price': unit_price,
                'main_unit_price': unit_values['main_unit_price'],
                'unit_price_after_tax': 0.0,
                'amount_oc': amount,
                'amount': amount,
                'discount_rate': discount_rate,
                'discount_amount_oc': discount_amount,
                'discount_amount': discount_amount,
                'vat_rate': vat_rate,
                'vat_amount_oc': tax_amount,
                'vat_amount': tax_amount,
                'exchange_rate_operator': unit_values['exchange_rate_operator'],
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
            # MISA callback only returns org_refid, not the real refid/ref_detail_id
            # generated for pu_order lines. Keep our IDs as the accounting IDs so
            # later PUVoucher lines can link back and accumulate received qty.
            'is_get_new_id': False,
            'org_refid': org_refid,
            'is_allow_group': False,
            'org_refno': self.name,
            'org_reftype': 301,
            'org_reftype_name': 'Don mua hang',
            'act_voucher_type': 0,
            'refid': org_refid,
            'branch_id': branch_id,
            'status': purchase_status_code,
            'order_status': purchase_status_code,
            'purchase_order_status': purchase_status_code,
            'status_name': purchase_status,
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

    def _misa_purchase_status_code(self, lines):
        total_qty = 0.0
        total_received = 0.0
        for line in lines:
            total_qty += float(line.product_qty or 0.0)
            total_received += self._misa_purchase_line_received_quantity(line)
        if total_qty and total_received >= total_qty:
            return 3
        if total_received > 0:
            return 2
        return 1

    def _misa_purchase_status_name(self, status_code):
        return {
            1: 'Chưa thực hiện',
            2: 'Đang thực hiện',
            3: 'Hoàn thành',
            4: 'Hủy bỏ',
        }.get(int(status_code or 1), 'Chưa thực hiện')

    def _misa_purchase_order_line_org_ref_detail_id(self, line):
        return str(uuid.uuid5(
            uuid.NAMESPACE_DNS,
            'misa_purchase_order_detail|%d|%d' % (self.id, line.id)
        ))

    def _misa_purchase_order_line_ref_detail_id(self, line):
        org_ref_detail_id = (line.misa_purchase_order_org_ref_detail_id or '').strip()
        ref_detail_id = (line.misa_purchase_order_ref_detail_id or '').strip()
        if ref_detail_id and line.misa_purchase_order_ref_detail_synced:
            if org_ref_detail_id and ref_detail_id != org_ref_detail_id:
                _logger.warning(
                    'Don mua %s dong %s co MISA detail ID %s khac org detail ID %s; dung MISA detail ID de link phieu nhap.',
                    self.name,
                    line.display_name,
                    ref_detail_id,
                    org_ref_detail_id,
                )
            return ref_detail_id
        if org_ref_detail_id:
            return org_ref_detail_id
        org_ref_detail_id = self._misa_purchase_order_line_org_ref_detail_id(line)
        line.sudo().write({'misa_purchase_order_org_ref_detail_id': org_ref_detail_id})
        return org_ref_detail_id

    def _misa_purchase_order_link_refid(self):
        self.ensure_one()
        org_refid = (self.misa_purchase_order_org_refid or '').strip()
        refid = (self.misa_purchase_order_refid or '').strip()
        if refid:
            if org_refid and refid != org_refid:
                _logger.warning(
                    'Don mua %s co MISA refid %s khac org_refid %s; dung MISA refid de link phieu nhap.',
                    self.name,
                    refid,
                    org_refid,
                )
            return refid
        return org_refid

    def _misa_purchase_order_lines_missing_ref_detail(self, lines):
        return lines.filtered(lambda line: not self._misa_purchase_order_line_ref_detail_id(line))

    def _misa_refresh_purchase_order_refs_from_logs(self):
        self.ensure_one()
        org_refid = (self.misa_purchase_order_org_refid or '').strip()
        if not org_refid:
            return
        line_helper = self.env['amis.callback.log.line']
        log_lines = self.env['amis.callback.log.line'].sudo().search([
            ('org_refid', '=', org_refid),
            ('success', '=', True),
        ], order='create_date asc, id asc')
        for log_line in log_lines:
            item = log_line._misa_callback_item()
            voucher_type = log_line._misa_callback_voucher_type(item)
            item_refno = log_line._misa_callback_refno(item)
            if voucher_type in (7, 18) or log_line._misa_refno_looks_like_inward(item_refno):
                continue
            if log_line._misa_callback_is_request_callback(voucher_type, item_refno):
                continue
            voucher_data = log_line._misa_callback_voucher_data(item)
            self._misa_apply_purchase_order_callback_item(line_helper, item, voucher_data)

        callback_logs = self.env['amis.callback.log'].sudo().search([
            ('data_type', '=', 22),
            ('data_payload', 'ilike', org_refid),
        ], order='received_at asc, id asc')
        for callback_log in callback_logs:
            for item in callback_log._parse_data_items(callback_log.data_payload):
                if not isinstance(item, dict):
                    continue
                item_refid = (item.get('org_refid') or item.get('refid') or '').strip()
                if item_refid != org_refid:
                    continue
                try:
                    voucher_type = int(item.get('voucher_type') or 0)
                except Exception:
                    voucher_type = 0
                item_refno = (item.get('org_refno') or item.get('refno') or '').strip()
                if voucher_type not in (0, 21) or line_helper._misa_refno_looks_like_inward(item_refno):
                    continue
                if line_helper._misa_callback_is_request_callback(voucher_type, item_refno):
                    continue
                voucher_data = line_helper._misa_callback_voucher_data(item)
                self._misa_apply_purchase_order_callback_item(line_helper, item, voucher_data)

    def _misa_apply_purchase_order_callback_item(self, line_helper, item, voucher_data):
        self.ensure_one()
        item = item or {}
        voucher_data = voucher_data or {}
        actual_refid = (
            voucher_data.get('refid') or item.get('refid') or item.get('misa_refid') or
            (self.misa_purchase_order_org_refid or '').strip()
        )
        vals = {'misa_purchase_order_synced': True}
        if actual_refid:
            vals['misa_purchase_order_refid'] = actual_refid
        self.sudo().write(vals)
        line_helper._apply_purchase_order_detail_ids(self, voucher_data)

    def _misa_purchase_line_received_quantity(self, line):
        qty_received = float(getattr(line, 'qty_received', 0.0) or 0.0)
        if qty_received:
            return qty_received
        moves = line.move_ids.filtered(
            lambda m: m.state == 'done'
            and m.picking_id
            and m.picking_id.picking_type_code == 'incoming'
        )
        return sum(float(move.product_uom._compute_quantity(move.quantity, line.product_uom) or 0.0) for move in moves)

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
            found = self._find_misa_account_object_by_id(config, existing_id)
            if found:
                return self._normalize_misa_account_object(found, partner)
            stale = self.env['amis.misa.vendor.cache'].sudo().search([
                ('config_id', '=', config.id),
                ('account_object_id', '=', existing_id),
                '|',
                ('is_deleted', '=', True),
                ('misa_inactive', '=', True),
            ], limit=1)
            if stale:
                state = 'đã xóa' if stale.is_deleted else 'ngừng sử dụng'
                raise UserError(
                    'Nhà cung cấp "%s" đang map với NCC MISA %s (%s). Vui lòng xử lý cache NCC trước khi sync.'
                    % (partner.display_name, state, existing_id)
                )
            return {
                'account_object_id': existing_id,
                'account_object_code': self._misa_partner_code(partner),
                'account_object_name': partner.display_name or partner.name or '',
            }

        partner_code = self._misa_partner_code(partner)
        found = self._find_misa_account_object_by_code_or_name(
            config,
            partner_code,
            partner.name or partner.display_name,
        )
        if found:
            return self._normalize_misa_account_object(found, partner)

        misa_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'misa_account_object|%d' % partner.id))
        branch_id = (config.misa_branch_id or '').strip()
        if not branch_id:
            raise UserError('Chưa cấu hình MISA Branch ID để đồng bộ nhà cung cấp.')
        code = partner_code
        name = (partner.display_name or partner.name or code).strip()
        account_object_type = 0 if partner.is_company or partner.company_type == 'company' else 1
        item = {
            'dictionary_type': 1,
            'branch_id': branch_id,
            'account_object_id': misa_id,
            'account_object_type': account_object_type,
            'account_object_code': code,
            'account_object_name': name,
            'account_object_address': partner.contact_address_complete or '',
            'address': partner.contact_address_complete or '',
            'country': partner.country_id.name or '',
            'company_tax_code': partner.vat or '',
            'due_time': 0,
            'tel': partner.phone or partner.mobile or '',
            'mobile': partner.mobile or partner.phone or '',
            'email_address': partner.email or '',
            'is_vendor': True,
            'is_customer': False,
            'is_employee': False,
            'is_same_address': False,
            'pay_account': '331',
            'receive_account': '131',
            'inactive': False,
            'agreement_salary': 0.0,
            'salary_coefficient': 0.0,
            'insurance_salary': 0.0,
            'maximize_debt_amount': 0.0,
            'receiptable_debt_amount': 0.0,
            'closing_amount': 0.0,
            'reftype': 0,
            'reftype_category': 0,
            'is_convert': False,
            'is_group': False,
            'is_remind_debt': True,
            'excel_row_index': 0,
            'is_valid': False,
            'auto_refno': False,
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

        cache, stale = self.env['amis.misa.unit.cache'].sudo().lookup_for_uom(config, uom)
        if cache:
            unit_id = (cache.unit_id or '').strip()
            unit_name = (cache.unit_name or name).strip()
            if unit_id:
                uom.sudo().write({'misa_unit_id': unit_id})
                return {'unit_id': unit_id, 'unit_name': unit_name}
        if stale:
            state = 'đã xóa' if stale.is_deleted else 'ngừng sử dụng'
            raise UserError(
                'ĐVT "%s" trùng với ĐVT MISA %s (%s). Vui lòng xử lý cache ĐVT trước khi sync.'
                % (name, state, stale.unit_id)
            )

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
        unit_id = (unit or {}).get('unit_id') or (getattr(uom, 'misa_unit_id', '') or '').strip()
        unit_name = (unit or {}).get('unit_name') or (uom.name if uom else '')

        if existing_id:
            cache, stale = self.env['amis.misa.inventory.cache'].sudo().lookup_for_product(config, product)
            if stale and stale.inventory_item_id == existing_id:
                state = 'da xoa' if stale.is_deleted else 'ngung su dung'
                raise UserError(
                    'San pham "%s" dang map voi hang hoa MISA %s (%s). Vui long cap nhat cache/xu ly mapping truoc khi sync.'
                    % (product.display_name, state, existing_id)
                )
            if cache and cache.inventory_item_id == existing_id:
                return cache.to_misa_item()
            return {
                'inventory_item_id': existing_id,
                'inventory_item_code': product.default_code or code,
                'inventory_item_name': name,
                'unit_id': unit_id,
                'unit_name': unit_name,
                'main_unit_id': unit_id,
                'main_unit_name': unit_name,
            }

        lock_name = 'amis_callback:inventory_item:%s:%s' % (self.env.cr.dbname, code)
        self.env.cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s)::bigint)", [lock_name])

        if hasattr(product, 'invalidate_recordset'):
            product.invalidate_recordset(['misa_inventory_item_id'])
        existing_id = (getattr(product, 'misa_inventory_item_id', '') or '').strip()
        if existing_id:
            return {
                'inventory_item_id': existing_id,
                'inventory_item_code': product.default_code or code,
                'inventory_item_name': name,
                'unit_id': unit_id,
                'unit_name': unit_name,
                'main_unit_id': unit_id,
                'main_unit_name': unit_name,
            }

        cache, stale = self.env['amis.misa.inventory.cache'].sudo().lookup_for_product(config, product)
        if cache:
            product.sudo().write({'misa_inventory_item_id': cache.inventory_item_id})
            if cache.product_id.id != product.id:
                cache.sudo().write({'product_id': product.id})
            cache_unit_name = (cache.unit_name or cache.main_unit_name or '').strip()
            if (
                cache.unit_id
                and uom
                and not (getattr(uom, 'misa_unit_id', '') or '').strip()
                and cache_unit_name
                and (uom.name or '').strip().casefold() == cache_unit_name.casefold()
            ):
                uom.sudo().write({'misa_unit_id': cache.unit_id})
            _logger.info('Mapped product %s to MISA inventory cache %s (%s)', code, cache.inventory_item_id, cache.inventory_item_name)
            return cache.to_misa_item()
        if stale:
            state = 'da xoa' if stale.is_deleted else 'ngung su dung'
            raise UserError(
                'San pham "%s" co ma "%s" trung voi hang hoa MISA %s (%s). Vui long xu ly cache truoc khi sync.'
                % (product.display_name, code, state, stale.inventory_item_id)
            )

        item_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'misa_inventory_item|%d' % product.id))
        unit_id = unit_id or ''
        unit_name = unit_name or ''
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
        return dict(item, **{
            'inventory_item_id': item_id,
            'inventory_item_code': code,
            'inventory_item_name': name,
        })

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
        cache = self.env['amis.misa.unit.cache'].sudo().search([
            ('config_id', '=', config.id),
            ('unit_id', '=', unit_id),
        ], limit=1)
        if cache:
            return cache.to_misa_item()
        return None

    def _misa_parse_list(self, value):
        if not value:
            return []
        parsed = value
        if isinstance(value, str):
            try:
                parsed = json.loads(value) if value.strip() else []
            except Exception:
                parsed = []
        if isinstance(parsed, dict):
            return [parsed]
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
        return []

    def _misa_float(self, value, default=0.0):
        try:
            if isinstance(value, str):
                value = value.replace(',', '.')
            return float(value)
        except Exception:
            return default

    def _misa_inventory_unit_converts(self, inventory_item):
        raw = (
            inventory_item.get('inventory_item_unit_convert')
            or inventory_item.get('inventory_item_unit_converts')
            or inventory_item.get('unit_convert')
            or inventory_item.get('unit_list')
            or []
        )
        return self._misa_parse_list(raw)

    def _misa_inventory_main_unit(self, config, inventory_item, fallback_unit=None):
        main_unit_id = (
            inventory_item.get('main_unit_id')
            or inventory_item.get('unit_id')
            or (fallback_unit or {}).get('unit_id')
            or ''
        )
        main_unit_name = (
            inventory_item.get('main_unit_name')
            or inventory_item.get('unit_name')
            or (fallback_unit or {}).get('unit_name')
            or ''
        )
        if main_unit_id and not main_unit_name:
            unit_item = self._find_misa_unit_by_id(config, main_unit_id)
            main_unit_name = (unit_item or {}).get('unit_name') or ''
        return main_unit_id, main_unit_name

    def _misa_convert_quantity(self, quantity, rate, operator):
        rate = self._misa_float(rate, 1.0) or 1.0
        operator = (operator or '*').strip() or '*'
        quantity = float(quantity or 0.0)
        if operator == '/':
            return quantity / rate
        return quantity * rate

    def _misa_convert_unit_price(self, unit_price, rate, operator):
        rate = self._misa_float(rate, 1.0) or 1.0
        operator = (operator or '*').strip() or '*'
        unit_price = float(unit_price or 0.0)
        if operator == '/':
            return unit_price * rate
        return unit_price / rate

    def _misa_unit_name_key(self, name):
        return (name or '').strip().casefold()

    def _misa_document_unit_values(self, config, inventory_item, odoo_uom, unit, quantity, unit_price):
        fallback_unit_id = ((unit or {}).get('unit_id') or (getattr(odoo_uom, 'misa_unit_id', '') or '')).strip()
        fallback_unit_name = ((unit or {}).get('unit_name') or (odoo_uom.name if odoo_uom else '') or '').strip()
        requested_unit_name = ((odoo_uom.name if odoo_uom else '') or fallback_unit_name).strip()
        requested_unit_name_key = self._misa_unit_name_key(requested_unit_name)
        main_unit_id, main_unit_name = self._misa_inventory_main_unit(config, inventory_item, fallback_unit=unit)
        item_unit_id = (inventory_item.get('unit_id') or '').strip()
        item_unit_name = (inventory_item.get('unit_name') or '').strip()

        unit_id = fallback_unit_id
        unit_name = fallback_unit_name

        def same_unit(candidate_id='', candidate_name=''):
            candidate_key = (candidate_id or '').strip().lower()
            candidate_name_key = self._misa_unit_name_key(candidate_name)
            fallback_key = (fallback_unit_id or '').strip().lower()
            return bool(
                candidate_key and fallback_key and candidate_key == fallback_key
            ) or bool(
                requested_unit_name_key and candidate_name_key
                and requested_unit_name_key == candidate_name_key
            )

        if item_unit_id and same_unit(item_unit_id, item_unit_name):
            unit_id = item_unit_id
            unit_name = item_unit_name or unit_name
        elif main_unit_id and same_unit(main_unit_id, main_unit_name):
            unit_id = main_unit_id
            unit_name = main_unit_name or unit_name

        rate = 1.0
        operator = '*'
        unit_key = (unit_id or '').strip().lower()
        unit_name_key = self._misa_unit_name_key(unit_name)
        main_unit_key = (main_unit_id or '').strip().lower()
        main_unit_name_key = self._misa_unit_name_key(main_unit_name)
        if unit_key and main_unit_key and unit_key == main_unit_key:
            pass
        elif unit_name_key and main_unit_name_key and unit_name_key == main_unit_name_key:
            if main_unit_id and not unit_id:
                unit_id = main_unit_id
            if main_unit_name and not unit_name:
                unit_name = main_unit_name
        else:
            for convert in self._misa_inventory_unit_converts(inventory_item):
                convert_unit_id = (convert.get('unit_id') or '').strip()
                convert_unit_name = (convert.get('unit_name') or convert.get('unit_name_convert') or '').strip()
                if convert_unit_id and not convert_unit_name:
                    unit_item = self._find_misa_unit_by_id(config, convert_unit_id)
                    convert_unit_name = (unit_item or {}).get('unit_name') or ''
                id_matches = bool(unit_key and convert_unit_id and unit_key == convert_unit_id.lower())
                name_matches = bool(
                    requested_unit_name_key
                    and convert_unit_name
                    and requested_unit_name_key == self._misa_unit_name_key(convert_unit_name)
                )
                if not id_matches and not name_matches:
                    continue
                unit_id = convert_unit_id or unit_id
                unit_name = convert_unit_name or unit_name
                rate = self._misa_float(convert.get('convert_rate'), 1.0) or 1.0
                operator = (convert.get('exchange_rate_operator') or '*').strip() or '*'
                break
            else:
                main_unit_id = main_unit_id or unit_id
                main_unit_name = main_unit_name or unit_name
                _logger.warning(
                    'Chưa tìm thấy quy đổi ĐVT MISA cho hàng hóa %s: Odoo=%s, MISA chính=%s',
                    inventory_item.get('inventory_item_code') or inventory_item.get('inventory_item_id') or '',
                    unit_name,
                    main_unit_name,
                )

        return {
            'unit_id': unit_id,
            'unit_name': unit_name,
            'main_unit_id': main_unit_id or unit_id,
            'main_unit_name': main_unit_name or unit_name,
            'main_convert_rate': rate,
            'exchange_rate_operator': operator,
            'main_quantity': self._misa_convert_quantity(quantity, rate, operator),
            'main_unit_price': self._misa_convert_unit_price(unit_price, rate, operator),
        }

    def _find_misa_account_object_by_code_or_name(self, config, partner_ref, partner_name):
        partner_ref = (partner_ref or '').strip()
        partner_name = (partner_name or '').strip()
        partner_ref_upper = partner_ref.upper()
        partner_name_upper = partner_name.upper()
        Cache = self.env['amis.misa.vendor.cache'].sudo()
        domain_base = [
            ('config_id', '=', config.id),
            ('is_deleted', '=', False),
            ('misa_inactive', '=', False),
        ]
        if partner_ref:
            cache = Cache.search(domain_base + [('account_object_code', '=', partner_ref)], limit=1)
            if cache:
                return cache.to_misa_item()
        if partner_name:
            cache = Cache.search(domain_base + [('account_object_name', '=ilike', partner_name)], limit=1)
            if cache:
                return cache.to_misa_item()
        if partner_name_upper:
            caches = Cache.search(domain_base + [('account_object_name', 'ilike', partner_name)], limit=5)
            for cache in caches:
                code = (cache.account_object_code or '').strip()
                name = (cache.account_object_name or '').strip()
                haystack = '%s %s' % (code.upper(), name.upper())
                if partner_name_upper in haystack:
                    return cache.to_misa_item()
        return None

    def _find_misa_account_object_by_id(self, config, account_object_id):
        account_object_id = (account_object_id or '').strip().lower()
        if not account_object_id:
            return None
        cache = self.env['amis.misa.vendor.cache'].sudo().search([
            ('config_id', '=', config.id),
            ('account_object_id', '=', account_object_id),
            ('is_deleted', '=', False),
            ('misa_inactive', '=', False),
        ], limit=1)
        if cache:
            return cache.to_misa_item()
        return None

    def _normalize_misa_account_object(self, item, partner):
        misa_id = (item.get('account_object_id') or '').strip()
        code = (item.get('account_object_code') or self._misa_partner_code(partner)).strip()
        name = (item.get('account_object_name') or partner.display_name or partner.name or '').strip()
        if misa_id and getattr(partner, 'misa_account_object_id', False) != misa_id:
            partner.sudo().write({'misa_account_object_id': misa_id})
            _logger.info('Auto-mapped PO vendor %s to MISA account_object_id=%s', partner.display_name, misa_id)
        return {
            'account_object_id': misa_id,
            'account_object_code': code,
            'account_object_name': name,
        }

    def _misa_partner_code(self, partner):
        partner.ensure_one()
        code = (partner.ref or '').strip()
        if code:
            return code[:50]
        tax_code = (partner.vat or '').strip()
        if tax_code:
            return tax_code[:50]
        registry = (getattr(partner, 'company_registry', '') or '').strip()
        if registry:
            return registry[:50]
        return self._misa_required_code('', fallback_prefix='NCC', fallback_id=partner.id)[:50]

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

    misa_purchase_order_org_ref_detail_id = fields.Char(
        string='MISA org_ref_detail_id Don mua hang',
        copy=False,
        help='org_ref_detail_id gui khi tao dong Don mua hang tren MISA.',
    )
    misa_purchase_order_ref_detail_id = fields.Char(
        string='MISA ref_detail_id Don mua hang',
        copy=False,
        help='ref_detail_id thuc te cua dong Don mua hang tren MISA, dung de link phieu mua/nhap kho.',
    )
    misa_purchase_order_ref_detail_synced = fields.Boolean(
        string='Da nhan ref_detail_id MISA Don mua hang',
        copy=False,
        help='Da xac nhan ref_detail_id dong Don mua hang tu callback MISA.',
    )
