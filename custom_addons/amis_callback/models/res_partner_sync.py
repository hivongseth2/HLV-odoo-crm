# -*- coding: utf-8 -*-
import logging
import uuid

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResPartnerAmisSync(models.Model):
    _inherit = 'res.partner'

    misa_skip_vendor_auto_sync = fields.Boolean(
        string='Bỏ qua tự động đồng bộ MISA',
        help=(
            'Không tự động đẩy nhà cung cấp này lên MISA và không để cron mirror '
            'MISA ghi đè thông tin, tài khoản ngân hàng của nhà cung cấp này.'
        ),
    )

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
            'hlv_business_role',
            'active',
            'is_company',
            'company_type',
            'misa_skip_vendor_auto_sync',
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
            if (
                job.status in ('pending', 'error')
                and (
                    not job.next_attempt_at
                    or job.next_attempt_at <= fields.Datetime.now()
                    or bool((vendor.misa_account_object_id or '').strip())
                )
            ):
                job._execute()

    def _misa_should_sync_vendor(self):
        self.ensure_one()
        partner = self.commercial_partner_id or self
        if partner != self:
            return False
        if not partner.name:
            return False
        if partner.misa_skip_vendor_auto_sync:
            return False
        business_role = getattr(partner, 'hlv_business_role', '') or ''
        return int(partner.supplier_rank or 0) > 0 or business_role == 'supplier'

    def _map_misa_vendor_from_mirror(self, config, job=None):
        self.ensure_one()
        if (self.misa_account_object_id or '').strip():
            return self.env['amis.misa.vendor.cache']
        cache = self.env['amis.misa.vendor.cache'].sudo().find_active_vendor_for_partner(
            config, self,
        )
        if not cache:
            return cache
        misa_id = (cache.account_object_id or '').strip()
        if not misa_id:
            return self.env['amis.misa.vendor.cache']
        self.with_context(skip_misa_partner_sync=True).sudo().write({
            'misa_account_object_id': misa_id,
        })
        if cache.partner_id.id != self.id:
            cache.sudo().write({'partner_id': self.id})
        if job:
            job.sudo().add_change_line(
                data_type='vendor',
                operation='map',
                odoo_model='res.partner',
                res_id=self.id,
                misa_id=misa_id,
                code=cache.account_object_code or '',
                name=cache.account_object_name or '',
                change_summary='Map ID MISA từ cache mirror trước khi đồng bộ NCC',
            )
        _logger.info(
            'Mapped Odoo vendor %s to MISA account_object_id=%s from mirror cache.',
            self.display_name,
            misa_id,
        )
        return cache

    def _push_misa_vendor_dictionary(self, config, job=None):
        self.ensure_one()
        if self.misa_skip_vendor_auto_sync:
            if job:
                job.sudo().add_change_line(
                    data_type='vendor',
                    operation='skip',
                    odoo_model='res.partner',
                    res_id=self.id,
                    misa_id=(self.misa_account_object_id or '').strip(),
                    code=self._misa_vendor_code(),
                    name=self.display_name or self.name or '',
                    change_summary='Bỏ qua vì NCC được đánh dấu không tự động đồng bộ MISA',
                )
            _logger.info('Bỏ qua đồng bộ nhà cung cấp %s sang MISA theo cờ trên liên hệ.', self.display_name)
            return 'skip'
        branch_id = (config.misa_branch_id or '').strip()
        if not branch_id:
            raise UserError('Chưa cấu hình MISA Branch ID để đồng bộ nhà cung cấp.')
        had_misa_id = bool((self.misa_account_object_id or '').strip())
        operation = 'update' if had_misa_id else 'create'
        item = self._misa_vendor_dictionary_item(branch_id=branch_id)
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
                change_summary='Đã đẩy sang MISA: mã NCC, tên NCC, mã số thuế, điện thoại, email, địa chỉ',
            )
        _logger.info(
            'Đã đồng bộ nhà cung cấp Odoo %s sang account_object MISA %s',
            self.display_name,
            item.get('account_object_code') or misa_id,
        )
        return operation

    def _misa_vendor_dictionary_item(self, branch_id=None):
        self.ensure_one()
        misa_id = (self.misa_account_object_id or '').strip()
        if not misa_id:
            misa_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'misa_account_object|%d' % self.id))

        code = self._misa_vendor_code()
        name = (self.display_name or self.name or code).strip()
        address = self.contact_address_complete or ''
        phone = self.phone or self.mobile or ''
        mobile = self.mobile or self.phone or ''
        account_object_type = 0 if self.is_company or self.company_type == 'company' else 1
        return {
            'dictionary_type': 1,
            'branch_id': branch_id or '',
            'account_object_id': misa_id,
            'account_object_type': account_object_type,
            'account_object_code': code,
            'account_object_name': name,
            'account_object_address': address,
            'address': address,
            'country': self.country_id.name or '',
            'company_tax_code': self.vat or '',
            'due_time': 0,
            'tel': phone,
            'mobile': mobile,
            'email_address': self.email or '',
            'is_vendor': True,
            'is_customer': bool(self.customer_rank),
            'is_employee': False,
            'is_same_address': False,
            'pay_account': '331',
            'receive_account': '131',
            'inactive': not bool(self.active),
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
