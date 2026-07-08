# -*- coding: utf-8 -*-
import json

from odoo import api, fields, models


class AmisMisaUnitCache(models.Model):
    _name = 'amis.misa.unit.cache'
    _description = 'Cache đơn vị tính MISA'
    _order = 'write_date desc, unit_name'
    _rec_name = 'display_name'

    config_id = fields.Many2one(
        'amis.callback.config',
        string='Cấu hình',
        required=True,
        ondelete='cascade',
        index=True,
    )
    uom_id = fields.Many2one(
        'uom.uom',
        string='ĐVT Odoo',
        index=True,
        ondelete='set null',
    )
    unit_id = fields.Char(string='ID MISA', required=True, index=True)
    unit_name = fields.Char(string='Tên ĐVT MISA', index=True)
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
            'config_unit_id_unique',
            'unique(config_id, unit_id)',
            'Mỗi cấu hình chỉ có một cache cho một unit_id MISA.',
        ),
    ]

    @api.depends('unit_name', 'unit_id')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.unit_name or rec.unit_id

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
    def _find_uom(self, unit_id, unit_name):
        Uom = self.env['uom.uom'].sudo().with_context(active_test=False)
        uom = Uom
        if unit_id and 'misa_unit_id' in Uom._fields:
            uom = Uom.search([('misa_unit_id', '=', unit_id)], limit=1)
        if not uom and unit_name:
            uom = Uom.search([('name', '=ilike', unit_name)], limit=1)
        return uom

    @api.model
    def _vals_from_misa_item(self, config, item):
        unit_id = (self._first(item, 'unit_id', 'id', 'ID') or '').strip()
        unit_name = (self._first(item, 'unit_name', 'name') or '').strip()
        uom = self._find_uom(unit_id, unit_name)
        return {
            'config_id': config.id,
            'uom_id': uom.id or False,
            'unit_id': unit_id,
            'unit_name': unit_name,
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
        unit_id = (self._first(item, 'unit_id', 'id', 'ID') or '').strip()
        if not config or not unit_id:
            return self
        vals = self._vals_from_misa_item(config, item)
        rec = self.sudo().search([
            ('config_id', '=', config.id),
            ('unit_id', '=', unit_id),
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
        unit_id = (
            self._first(item, 'unit_id', 'id', 'ID')
            or self._first(payload, 'unit_id', 'id', 'ID')
            or ''
        ).strip()
        if not config or not unit_id:
            return self
        unit_name = (self._first(payload, 'unit_name', 'name') or '').strip()
        rec = self.sudo().search([
            ('config_id', '=', config.id),
            ('unit_id', '=', unit_id),
        ], limit=1)
        vals = {
            'is_deleted': True,
            'misa_deleted_at': self._first(item, 'delete_date', 'deleted_date', 'deleted_at') or '',
            'last_seen_at': fields.Datetime.now(),
        }
        if unit_name:
            vals['unit_name'] = unit_name
        if payload:
            vals['raw_json'] = json.dumps(payload, ensure_ascii=False, default=str)
        if rec:
            rec.write(vals)
            return rec
        vals.update({
            'config_id': config.id,
            'unit_id': unit_id,
            'unit_name': unit_name,
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
            'unit_id': self.unit_id,
            'unit_name': self.unit_name or '',
            'inactive': bool(self.misa_inactive),
        })
        return item

    @api.model
    def lookup_for_uom(self, config, uom):
        Cache = self.sudo()
        existing_id = (getattr(uom, 'misa_unit_id', '') or '').strip() if uom else ''
        name = (uom.name or '').strip() if uom else ''
        stale = Cache.browse()

        if existing_id:
            by_id = Cache.search([
                ('config_id', '=', config.id),
                ('unit_id', '=', existing_id),
            ], limit=1)
            if by_id:
                if not by_id.is_deleted and not by_id.misa_inactive:
                    return by_id, stale
                stale = by_id

        if name:
            by_name = Cache.search([
                ('config_id', '=', config.id),
                ('unit_name', '=ilike', name),
            ], order='is_deleted asc, misa_inactive asc, write_date desc', limit=5)
            active = by_name.filtered(lambda rec: not rec.is_deleted and not rec.misa_inactive)[:1]
            if active:
                return active, stale
            if not stale and by_name:
                stale = by_name[0]

        return Cache.browse(), stale
