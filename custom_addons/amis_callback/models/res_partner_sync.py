# -*- coding: utf-8 -*-
import logging
import uuid

from odoo import api, models

_logger = logging.getLogger(__name__)


class ResPartnerAmisSync(models.Model):
    _inherit = 'res.partner'

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        if not self.env.context.get('skip_misa_partner_sync'):
            partners._sync_misa_vendor_after_save()
        return partners

    def write(self, vals):
        result = super().write(vals)
        if (
            not self.env.context.get('skip_misa_partner_sync')
            and self._misa_vendor_sync_fields(vals)
        ):
            self._sync_misa_vendor_after_save()
        return result

    def _misa_vendor_sync_fields(self, vals):
        watched_fields = {
            'name',
            'ref',
            'vat',
            'phone',
            'mobile',
            'email',
            'street',
            'street2',
            'city',
            'state_id',
            'country_id',
            'supplier_rank',
            'customer_rank',
            'active',
            'is_company',
            'company_type',
        }
        return bool(watched_fields.intersection(vals))

    def _sync_misa_vendor_after_save(self):
        vendors = self.sudo().filtered(lambda partner: partner._misa_should_sync_vendor())
        if not vendors:
            return

        config = self.env['amis.callback.config'].sudo().ensure_singleton()
        if not config:
            _logger.info('Skip MISA vendor sync after partner save: no AMIS callback config.')
            return

        for vendor in vendors:
            job = self.env['amis.catalog.sync.job'].sudo().enqueue_vendor_to_misa(
                config,
                vendor,
                trigger='partner_save',
            )
            _logger.info('Enqueued MISA vendor sync job %s for partner %s', job.id, vendor.display_name)

    def _misa_should_sync_vendor(self):
        self.ensure_one()
        partner = self.commercial_partner_id or self
        if partner != self:
            return False
        if not partner.name:
            return False
        return int(partner.supplier_rank or 0) > 0

    def _push_misa_vendor_dictionary(self, config, job=None):
        self.ensure_one()
        had_misa_id = bool((self.misa_account_object_id or '').strip())
        operation = 'update' if had_misa_id else 'create'
        item = self._misa_vendor_dictionary_item()
        config.push_dictionary([item])
        config.clear_dictionary_cache([1])
        misa_id = item.get('account_object_id') or ''
        if misa_id and (self.misa_account_object_id or '').strip() != misa_id:
            self.with_context(skip_misa_partner_sync=True).sudo().write({
                'misa_account_object_id': misa_id,
            })
        if job:
            job.sudo().add_change_line(
                data_type='vendor',
                operation=operation,
                odoo_model='res.partner',
                res_id=self.id,
                misa_id=misa_id,
                code=item.get('account_object_code') or '',
                name=item.get('account_object_name') or '',
                change_summary='pushed to MISA: account_object_code, account_object_name, tax, phone, email, address',
            )
        _logger.info(
            'Synced Odoo vendor %s to MISA account_object %s',
            self.display_name,
            item.get('account_object_code') or misa_id,
        )
        return operation

    def _misa_vendor_dictionary_item(self):
        self.ensure_one()
        misa_id = (self.misa_account_object_id or '').strip()
        if not misa_id:
            misa_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'misa_account_object|%d' % self.id))

        code = self._misa_vendor_code()
        name = (self.display_name or self.name or code).strip()
        address = self.contact_address_complete or ''
        phone = self.phone or self.mobile or ''
        mobile = self.mobile or self.phone or ''
        return {
            'dictionary_type': 1,
            'account_object_id': misa_id,
            'account_object_code': code,
            'account_object_name': name,
            'account_object_address': address,
            'address': address,
            'company_tax_code': self.vat or '',
            'tel': phone,
            'mobile': mobile,
            'email_address': self.email or '',
            'is_vendor': True,
            'is_customer': bool(self.customer_rank),
            'is_employee': False,
            'inactive': not bool(self.active),
            'state': 1,
        }

    def _misa_vendor_code(self):
        self.ensure_one()
        code = (self.ref or '').strip()
        if code:
            return code[:50]
        tax_code = (self.vat or '').strip()
        if tax_code:
            return tax_code[:50]
        registry = (getattr(self, 'company_registry', '') or '').strip()
        if registry:
            return registry[:50]
        return ('NCC%05d' % int(self.id or 0))[:50]
