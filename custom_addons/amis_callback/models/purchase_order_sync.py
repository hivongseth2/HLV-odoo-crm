# -*- coding: utf-8 -*-
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
            'misa_purchase_order_synced': True,
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

        org_refid = (self.misa_purchase_order_org_refid or '').strip()
        if not org_refid:
            org_refid = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'misa_purchase_order|%d' % self.id))
            self.sudo().write({'misa_purchase_order_org_refid': org_refid})

        account_object_id = (getattr(partner, 'misa_account_object_id', '') or '').strip()
        account_object_code = (partner.ref or partner.name or '').strip()
        account_object_name = (partner.display_name or partner.name or '').strip()

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

            inventory_item_id = (getattr(product, 'misa_inventory_item_id', '') or '').strip()
            unit_id = (getattr(line.product_uom, 'misa_unit_id', '') or '').strip()
            ref_detail_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'misa_purchase_order_detail|%d|%d' % (self.id, line.id)))

            line_payload = {
                'ref_detail_id': ref_detail_id,
                'refid': org_refid,
                'sort_order': idx,
                'is_description': False,
                'inventory_item_code': product.default_code or str(product.id),
                'inventory_item_name': product.display_name,
                'description': line.name or product.display_name,
                'unit_name': line.product_uom.name,
                'main_unit_name': line.product_uom.name,
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
                'inventory_item_type': 0,
                'is_allow_duplicate_serial_number': False,
                'is_follow_serial_number': False,
                'is_description_import': False,
                'state': 0,
            }
            if inventory_item_id:
                line_payload['inventory_item_id'] = inventory_item_id
            if unit_id:
                line_payload['unit_id'] = unit_id
                line_payload['main_unit_id'] = unit_id
            detail.append(line_payload)

        refdate = self._misa_purchase_datetime(self.date_order or fields.Datetime.now())
        branch_id = (config.misa_branch_id or '').strip() or ZERO_UUID
        now_ms = int(fields.Datetime.now().timestamp() * 1000)

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
            'account_object_name': account_object_name,
            'account_object_address': partner.contact_address_complete or '',
            'account_object_tax_code': partner.vat or '',
            'account_object_code': account_object_code,
            'journal_memo': getattr(self, 'notes', False) or self.origin or ('Don mua hang %s' % self.name),
            'currency_id': self.currency_id.name or 'VND',
            'reftype': 301,
            'auto_refno': False,
            'state': 0,
            'detail': detail,
        }
        if account_object_id:
            voucher['account_object_id'] = account_object_id
        return voucher

    def _misa_purchase_line_vat_rate(self, line):
        taxes = line.taxes_id.filtered(lambda t: t.amount_type == 'percent')
        if taxes:
            return float(taxes[0].amount or 0.0)
        return 0.0

    def _misa_purchase_datetime(self, value):
        if not value:
            value = fields.Datetime.now()
        if isinstance(value, str):
            value = fields.Datetime.from_string(value)
        localized = fields.Datetime.context_timestamp(self, value)
        return localized.isoformat()
