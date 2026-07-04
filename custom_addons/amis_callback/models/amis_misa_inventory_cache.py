# -*- coding: utf-8 -*-
import json

from odoo import api, fields, models


class AmisMisaInventoryCache(models.Model):
    _name = 'amis.misa.inventory.cache'
    _description = 'Cache hàng hóa MISA'
    _order = 'write_date desc, inventory_item_code'
    _rec_name = 'display_name'

    config_id = fields.Many2one(
        'amis.callback.config',
        string='Cấu hình',
        required=True,
        ondelete='cascade',
        index=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Sản phẩm Odoo',
        index=True,
        ondelete='set null',
    )
    inventory_item_id = fields.Char(string='ID MISA', required=True, index=True)
    inventory_item_code = fields.Char(string='Mã hàng MISA', index=True)
    inventory_item_name = fields.Char(string='Tên hàng MISA')
    unit_id = fields.Char(string='ID ĐVT')
    unit_name = fields.Char(string='ĐVT')
    main_unit_id = fields.Char(string='ID ĐVT chính')
    main_unit_name = fields.Char(string='ĐVT chính')
    unit_convert_json = fields.Text(string='Quy đổi ĐVT')
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
            'config_inventory_item_id_unique',
            'unique(config_id, inventory_item_id)',
            'Mỗi cấu hình chỉ có một cache cho một inventory_item_id MISA.',
        ),
    ]

    @api.depends('inventory_item_code', 'inventory_item_name')
    def _compute_display_name(self):
        for rec in self:
            code = (rec.inventory_item_code or '').strip()
            name = (rec.inventory_item_name or '').strip()
            rec.display_name = '[%s] %s' % (code, name) if code and name else (
                code or name or rec.inventory_item_id
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
    def _unit_convert_text(self, item):
        raw = (
            item.get('inventory_item_unit_convert')
            or item.get('inventory_item_unit_converts')
            or item.get('unit_convert')
            or item.get('unit_list')
            or []
        )
        if isinstance(raw, str):
            return raw
        if raw:
            try:
                return json.dumps(raw, ensure_ascii=False, default=str)
            except Exception:
                return ''
        return ''

    @api.model
    def _find_product(self, item_id, code):
        Product = self.env['product.product'].sudo().with_context(active_test=False)
        product = Product
        if item_id and 'misa_inventory_item_id' in Product._fields:
            product = Product.search([('misa_inventory_item_id', '=', item_id)], limit=1)
        if not product and code:
            product = Product.search([('default_code', '=', code)], limit=1)
        return product

    @api.model
    def _vals_from_misa_item(self, config, item):
        item_id = (self._first(item, 'inventory_item_id', 'id', 'ID') or '').strip()
        code = (self._first(item, 'inventory_item_code', 'code') or '').strip()
        name = (self._first(item, 'inventory_item_name', 'name') or '').strip()
        product = self._find_product(item_id, code)
        return {
            'config_id': config.id,
            'product_id': product.id or False,
            'inventory_item_id': item_id,
            'inventory_item_code': code,
            'inventory_item_name': name,
            'unit_id': (self._first(item, 'unit_id') or '').strip(),
            'unit_name': (self._first(item, 'unit_name') or '').strip(),
            'main_unit_id': (self._first(item, 'main_unit_id') or self._first(item, 'unit_id') or '').strip(),
            'main_unit_name': (self._first(item, 'main_unit_name') or self._first(item, 'unit_name') or '').strip(),
            'unit_convert_json': self._unit_convert_text(item),
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
        item_id = (self._first(item, 'inventory_item_id', 'id', 'ID') or '').strip()
        if not config or not item_id:
            return self
        vals = self._vals_from_misa_item(config, item)
        rec = self.sudo().search([
            ('config_id', '=', config.id),
            ('inventory_item_id', '=', item_id),
        ], limit=1)
        if rec:
            rec.write(vals)
            return rec
        return self.sudo().create(vals)

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
            self._first(item, 'inventory_item_id', 'id', 'ID')
            or self._first(payload, 'inventory_item_id', 'id', 'ID')
            or ''
        ).strip()
        if not config or not item_id:
            return self
        code = (self._first(payload, 'inventory_item_code', 'code') or '').strip()
        name = (self._first(payload, 'inventory_item_name', 'name') or '').strip()
        rec = self.sudo().search([
            ('config_id', '=', config.id),
            ('inventory_item_id', '=', item_id),
        ], limit=1)
        vals = {
            'is_deleted': True,
            'misa_deleted_at': self._first(item, 'delete_date', 'deleted_date', 'deleted_at') or '',
            'last_seen_at': fields.Datetime.now(),
        }
        if code:
            vals['inventory_item_code'] = code
        if name:
            vals['inventory_item_name'] = name
        if payload:
            vals['raw_json'] = json.dumps(payload, ensure_ascii=False, default=str)
        if rec:
            rec.write(vals)
            return rec
        vals.update({
            'config_id': config.id,
            'inventory_item_id': item_id,
            'inventory_item_code': code,
            'inventory_item_name': name,
        })
        return self.sudo().create(vals)

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
            'inventory_item_id': self.inventory_item_id,
            'inventory_item_code': self.inventory_item_code or '',
            'inventory_item_name': self.inventory_item_name or '',
            'unit_id': self.unit_id or '',
            'unit_name': self.unit_name or '',
            'main_unit_id': self.main_unit_id or self.unit_id or '',
            'main_unit_name': self.main_unit_name or self.unit_name or '',
            'inactive': bool(self.misa_inactive),
        })
        if self.unit_convert_json:
            try:
                item['inventory_item_unit_convert'] = json.loads(self.unit_convert_json)
            except Exception:
                item['inventory_item_unit_convert'] = self.unit_convert_json
        return item

    @api.model
    def lookup_for_product(self, config, product):
        Cache = self.sudo()
        existing_id = (getattr(product, 'misa_inventory_item_id', '') or '').strip()
        code = (getattr(product, 'default_code', '') or '').strip()
        stale = Cache.browse()

        if existing_id:
            by_id = Cache.search([
                ('config_id', '=', config.id),
                ('inventory_item_id', '=', existing_id),
            ], limit=1)
            if by_id:
                if not by_id.is_deleted and not by_id.misa_inactive:
                    return by_id, stale
                stale = by_id

        if code:
            by_code = Cache.search([
                ('config_id', '=', config.id),
                ('inventory_item_code', '=', code),
            ], order='is_deleted asc, misa_inactive asc, write_date desc', limit=5)
            active = by_code.filtered(lambda rec: not rec.is_deleted and not rec.misa_inactive)[:1]
            if active:
                return active, stale
            if not stale and by_code:
                stale = by_code[0]

        return Cache.browse(), stale
