# -*- coding: utf-8 -*-
import json
import re

from odoo import api, fields, models


class AmisMisaVendorCache(models.Model):
    _name = 'amis.misa.vendor.cache'
    _description = 'Cache nhà cung cấp MISA'
    _order = 'write_date desc, account_object_code'
    _rec_name = 'display_name'

    config_id = fields.Many2one(
        'amis.callback.config',
        string='Cấu hình',
        required=True,
        ondelete='cascade',
        index=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Nhà cung cấp Odoo',
        index=True,
        ondelete='set null',
    )
    account_object_id = fields.Char(string='ID MISA', required=True, index=True)
    account_object_code = fields.Char(string='Mã NCC MISA', index=True)
    account_object_name = fields.Char(string='Tên NCC MISA')
    company_tax_code = fields.Char(string='Mã số thuế', index=True)
    tel = fields.Char(string='Điện thoại')
    mobile = fields.Char(string='Di động')
    email = fields.Char(string='Email')
    address = fields.Char(string='Địa chỉ')
    province_or_city = fields.Char(string='Tỉnh/Thành')
    district = fields.Char(string='Quận/Huyện')
    ward_or_commune = fields.Char(string='Phường/Xã')
    country = fields.Char(string='Quốc gia')
    is_vendor = fields.Boolean(string='Là nhà cung cấp', index=True)
    is_customer = fields.Boolean(string='Là khách hàng', index=True)
    bank_account_json = fields.Text(string='Dữ liệu ngân hàng MISA')
    bank_line_ids = fields.One2many(
        'amis.misa.vendor.bank.cache',
        'vendor_cache_id',
        string='Tài khoản ngân hàng',
    )
    misa_inactive = fields.Boolean(string='Ngừng sử dụng trên MISA', index=True)
    is_deleted = fields.Boolean(string='Đã xóa trên MISA', index=True)
    misa_deleted_at = fields.Char(string='Ngày xóa trên MISA')
    misa_modified_date = fields.Char(string='Ngày sửa trên MISA')
    misa_created_date = fields.Char(string='Ngày tạo trên MISA')
    last_seen_at = fields.Datetime(string='Lần cuối thấy từ MISA', default=fields.Datetime.now)
    raw_json = fields.Text(string='Dữ liệu gốc MISA')
    display_name = fields.Char(string='Tên hiển thị', compute='_compute_display_name', store=True)

    _sql_constraints = [
        (
            'config_account_object_id_unique',
            'unique(config_id, account_object_id)',
            'Mỗi cấu hình chỉ có một cache cho một account_object_id MISA.',
        ),
    ]

    @api.depends('account_object_code', 'account_object_name')
    def _compute_display_name(self):
        for rec in self:
            code = (rec.account_object_code or '').strip()
            name = (rec.account_object_name or '').strip()
            rec.display_name = '[%s] %s' % (code, name) if code and name else (
                code or name or rec.account_object_id
            )

    @api.model
    def _first(self, item, *keys):
        for key in keys:
            value = item.get(key)
            if value not in (None, False, ''):
                return value
        return ''

    @api.model
    def _misa_truthy(self, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {'1', 'true', 'yes', 'y', 'co', 'có'}
        return bool(value)

    @api.model
    def _match_code(self, value):
        return ' '.join(str(value or '').strip().upper().split())

    @api.model
    def _match_tax(self, value):
        return re.sub(r'[^0-9A-Z]+', '', str(value or '').strip().upper())

    @api.model
    def _find_partner(self, item_id, code, tax_code):
        Partner = self.env['res.partner'].sudo().with_context(active_test=False)
        partner = Partner
        supplier_domain = [('parent_id', '=', False), ('supplier_rank', '>', 0)]
        if 'hlv_business_role' in Partner._fields:
            supplier_domain = [
                ('parent_id', '=', False),
                '|',
                ('supplier_rank', '>', 0),
                ('hlv_business_role', '=', 'supplier'),
            ]
        if item_id and 'misa_account_object_id' in Partner._fields:
            partner = Partner.search(supplier_domain + [('misa_account_object_id', '=', item_id)], limit=1)
        if not partner and code:
            partner = Partner.search(supplier_domain + [('ref', '=', code)], limit=1)
        if not partner and tax_code:
            partner = Partner.search(supplier_domain + [('vat', '=', tax_code)], limit=2)
            if len(partner) > 1:
                partner = Partner
        return partner[:1]

    @api.model
    def _bank_items(self, item):
        bank_items = []
        raw = item.get('account_object_bank_account')
        if raw:
            parsed = raw
            if isinstance(raw, str):
                raw_text = raw.strip()
                try:
                    parsed = json.loads(raw_text) if raw_text else []
                except Exception:
                    parsed = []
            if isinstance(parsed, dict):
                parsed = (
                    parsed.get('data')
                    or parsed.get('Data')
                    or parsed.get('items')
                    or parsed.get('Items')
                    or [parsed]
                )
            if isinstance(parsed, list):
                bank_items.extend([bank for bank in parsed if isinstance(bank, dict)])

        single_bank = {
            'bank_account_number': item.get('bank_account') or item.get('bank_account_number'),
            'bank_name': item.get('bank_name'),
            'bank_branch_name': item.get('bank_branch_name'),
            'bank_province_or_city': item.get('bank_province_or_city'),
            'account_holder': item.get('account_object_name'),
        }
        if any((value or '').strip() if isinstance(value, str) else value for value in single_bank.values()):
            bank_items.append(single_bank)

        seen = set()
        result = []
        for bank_item in bank_items:
            acc_number = str(
                bank_item.get('bank_account_number')
                or bank_item.get('account_number')
                or bank_item.get('bank_account')
                or bank_item.get('acc_number')
                or ''
            ).strip()
            if not acc_number or acc_number in seen:
                continue
            seen.add(acc_number)
            result.append(bank_item)
        return result

    @api.model
    def _bank_json_text(self, item):
        bank_items = self._bank_items(item)
        if not bank_items:
            return ''
        return json.dumps(bank_items, ensure_ascii=False, default=str)

    @api.model
    def _vals_from_misa_item(self, config, item):
        item_id = (self._first(item, 'account_object_id', 'id', 'ID') or '').strip()
        code = (self._first(item, 'account_object_code', 'code') or '').strip()
        name = (self._first(item, 'account_object_name', 'name') or '').strip()
        tax_code = (self._first(item, 'company_tax_code', 'tax_code', 'vat') or '').strip()
        partner = self._find_partner(item_id, code, tax_code)
        return {
            'config_id': config.id,
            'partner_id': partner.id or False,
            'account_object_id': item_id,
            'account_object_code': code,
            'account_object_name': name,
            'company_tax_code': tax_code,
            'tel': (self._first(item, 'tel', 'phone') or '').strip(),
            'mobile': (self._first(item, 'mobile') or '').strip(),
            'email': (self._first(item, 'email_address', 'email') or '').strip(),
            'address': (self._first(item, 'account_object_address', 'address') or '').strip(),
            'province_or_city': (self._first(item, 'province_or_city') or '').strip(),
            'district': (self._first(item, 'district') or '').strip(),
            'ward_or_commune': (self._first(item, 'ward_or_commune') or '').strip(),
            'country': (self._first(item, 'country') or '').strip(),
            'is_vendor': self._misa_truthy(item.get('is_vendor')),
            'is_customer': self._misa_truthy(item.get('is_customer')),
            'bank_account_json': self._bank_json_text(item),
            'misa_inactive': self._misa_truthy(item.get('inactive')),
            'is_deleted': False,
            'misa_deleted_at': False,
            'misa_modified_date': (
                self._first(item, 'modified_date', 'modified_time', 'modified_at', 'last_modified_date') or ''
            ),
            'misa_created_date': (self._first(item, 'created_date', 'created_time', 'created_at') or ''),
            'last_seen_at': fields.Datetime.now(),
            'raw_json': json.dumps(item, ensure_ascii=False, default=str),
        }

    @api.model
    def upsert_from_misa_item(self, config, item):
        item_id = (self._first(item, 'account_object_id', 'id', 'ID') or '').strip()
        if not config or not item_id:
            return self
        vals = self._vals_from_misa_item(config, item)
        rec = self.sudo().search([
            ('config_id', '=', config.id),
            ('account_object_id', '=', item_id),
        ], limit=1)
        if rec:
            rec.write(vals)
        else:
            rec = self.sudo().create(vals)
        rec._sync_bank_cache_lines(item)
        return rec

    @api.model
    def _deleted_payload(self, item):
        payload = item.get('data') or item.get('Data') or item.get('raw_data') or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload) if payload.strip() else {}
            except Exception:
                payload = {}
        if isinstance(payload, list):
            payload = payload[0] if payload and isinstance(payload[0], dict) else {}
        return payload if isinstance(payload, dict) else {}

    @api.model
    def mark_deleted_from_misa_item(self, config, item):
        payload = self._deleted_payload(item)
        item_id = (
            self._first(item, 'account_object_id', 'id', 'ID')
            or self._first(payload, 'account_object_id', 'id', 'ID')
            or ''
        ).strip()
        if not config or not item_id:
            return self
        code = (self._first(payload, 'account_object_code', 'code') or '').strip()
        name = (self._first(payload, 'account_object_name', 'name') or '').strip()
        rec = self.sudo().search([
            ('config_id', '=', config.id),
            ('account_object_id', '=', item_id),
        ], limit=1)
        vals = {
            'is_deleted': True,
            'misa_deleted_at': self._first(item, 'delete_date', 'deleted_date', 'deleted_at') or '',
            'last_seen_at': fields.Datetime.now(),
        }
        if code:
            vals['account_object_code'] = code
        if name:
            vals['account_object_name'] = name
        if payload:
            vals['raw_json'] = json.dumps(payload, ensure_ascii=False, default=str)
        if rec:
            rec.write(vals)
            return rec
        vals.update({
            'config_id': config.id,
            'account_object_id': item_id,
            'account_object_code': code,
            'account_object_name': name,
        })
        return self.sudo().create(vals)

    def _sync_bank_cache_lines(self, item):
        self.ensure_one()
        BankCache = self.env['amis.misa.vendor.bank.cache'].sudo()
        seen = set()
        for bank_item in self._bank_items(item):
            acc_number = str(
                bank_item.get('bank_account_number')
                or bank_item.get('account_number')
                or bank_item.get('bank_account')
                or bank_item.get('acc_number')
                or ''
            ).strip()
            if not acc_number:
                continue
            seen.add(acc_number)
            vals = BankCache._vals_from_misa_bank(self, bank_item)
            line = BankCache.search([
                ('vendor_cache_id', '=', self.id),
                ('acc_number', '=', acc_number),
            ], limit=1)
            if line:
                line.write(vals)
            else:
                BankCache.create(vals)
        if seen:
            BankCache.search([
                ('vendor_cache_id', '=', self.id),
                ('acc_number', 'not in', list(seen)),
            ]).write({'active': False})

    def to_misa_item(self):
        self.ensure_one()
        item = {}
        if self.raw_json:
            try:
                parsed = json.loads(self.raw_json)
                if isinstance(parsed, dict):
                    item = parsed
            except Exception:
                item = {}
        item.update({
            'account_object_id': self.account_object_id,
            'account_object_code': self.account_object_code or '',
            'account_object_name': self.account_object_name or '',
            'company_tax_code': self.company_tax_code or '',
            'tel': self.tel or '',
            'mobile': self.mobile or '',
            'email_address': self.email or '',
            'account_object_address': self.address or '',
            'address': self.address or '',
            'province_or_city': self.province_or_city or '',
            'district': self.district or '',
            'ward_or_commune': self.ward_or_commune or '',
            'country': self.country or '',
            'is_vendor': bool(self.is_vendor),
            'is_customer': bool(self.is_customer),
            'inactive': bool(self.misa_inactive),
        })
        if self.bank_account_json:
            item['account_object_bank_account'] = self.bank_account_json
        return item

    @api.model
    def lookup_for_partner(self, config, partner):
        Cache = self.sudo()
        existing_id = (getattr(partner, 'misa_account_object_id', '') or '').strip() if partner else ''
        code = (partner.ref or '').strip() if partner else ''
        tax = (partner.vat or '').strip() if partner else ''
        stale = Cache.browse()

        if existing_id:
            by_id = Cache.search([
                ('config_id', '=', config.id),
                ('account_object_id', '=', existing_id),
            ], limit=1)
            if by_id:
                if not by_id.is_deleted and not by_id.misa_inactive:
                    return by_id, stale
                stale = by_id

        if code:
            by_code = Cache.search([
                ('config_id', '=', config.id),
                ('account_object_code', '=', code),
            ], order='is_deleted asc, misa_inactive asc, write_date desc', limit=5)
            active = by_code.filtered(lambda rec: not rec.is_deleted and not rec.misa_inactive)[:1]
            if active:
                return active, stale
            if not stale and by_code:
                stale = by_code[0]

        if tax:
            by_tax = Cache.search([
                ('config_id', '=', config.id),
                ('company_tax_code', '=', tax),
            ], order='is_deleted asc, misa_inactive asc, write_date desc', limit=5)
            active = by_tax.filtered(lambda rec: not rec.is_deleted and not rec.misa_inactive)[:1]
            if active:
                return active, stale
            if not stale and by_tax:
                stale = by_tax[0]

        return Cache.browse(), stale


class AmisMisaVendorBankCache(models.Model):
    _name = 'amis.misa.vendor.bank.cache'
    _description = 'Cache tài khoản ngân hàng MISA'
    _order = 'active desc, acc_number'

    active = fields.Boolean(string='Đang dùng', default=True, index=True)
    vendor_cache_id = fields.Many2one(
        'amis.misa.vendor.cache',
        string='Cache nhà cung cấp',
        required=True,
        ondelete='cascade',
        index=True,
    )
    config_id = fields.Many2one(
        related='vendor_cache_id.config_id',
        string='Cấu hình',
        store=True,
        index=True,
    )
    partner_id = fields.Many2one(
        related='vendor_cache_id.partner_id',
        string='Nhà cung cấp Odoo',
        store=True,
        index=True,
    )
    partner_bank_id = fields.Many2one(
        'res.partner.bank',
        string='Tài khoản Odoo',
        index=True,
        ondelete='set null',
    )
    account_object_id = fields.Char(
        related='vendor_cache_id.account_object_id',
        string='ID NCC MISA',
        store=True,
        index=True,
    )
    acc_number = fields.Char(string='Số tài khoản', required=True, index=True)
    bank_name = fields.Char(string='Ngân hàng')
    bank_code = fields.Char(string='Mã ngân hàng')
    branch_name = fields.Char(string='Chi nhánh')
    bank_city = fields.Char(string='Tỉnh/Thành ngân hàng')
    account_holder = fields.Char(string='Chủ tài khoản')
    raw_json = fields.Text(string='Dữ liệu gốc MISA')

    _sql_constraints = [
        (
            'vendor_cache_acc_number_unique',
            'unique(vendor_cache_id, acc_number)',
            'Mỗi cache nhà cung cấp chỉ có một dòng cho một số tài khoản.',
        ),
    ]

    @api.model
    def _vals_from_misa_bank(self, vendor_cache, bank_item):
        acc_number = str(
            bank_item.get('bank_account_number')
            or bank_item.get('account_number')
            or bank_item.get('bank_account')
            or bank_item.get('acc_number')
            or ''
        ).strip()
        bank_name = str(bank_item.get('bank_name') or '').strip()
        bank_code = str(bank_item.get('bank_code') or bank_item.get('bank_id') or '').strip()
        branch_name = str(bank_item.get('bank_branch_name') or bank_item.get('branch_name') or '').strip()
        bank_city = str(
            bank_item.get('bank_province_or_city')
            or bank_item.get('province_or_city')
            or bank_item.get('provin_or_city')
            or ''
        ).strip()
        holder = str(
            bank_item.get('account_holder')
            or bank_item.get('account_holder_name')
            or vendor_cache.account_object_name
            or ''
        ).strip()

        partner_bank = self.env['res.partner.bank'].sudo()
        if vendor_cache.partner_id and acc_number:
            partner_bank = partner_bank.search([
                ('partner_id', '=', vendor_cache.partner_id.id),
                ('acc_number', '=', acc_number),
            ], limit=1)

        return {
            'active': True,
            'vendor_cache_id': vendor_cache.id,
            'partner_bank_id': partner_bank.id or False,
            'acc_number': acc_number,
            'bank_name': bank_name,
            'bank_code': bank_code,
            'branch_name': branch_name,
            'bank_city': bank_city,
            'account_holder': holder,
            'raw_json': json.dumps(bank_item, ensure_ascii=False, default=str),
        }
