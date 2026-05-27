# -*- coding: utf-8 -*-
"""
models/shopee_category.py

Cache cây danh mục Shopee theo từng shop để dùng làm Many2one selector
trong wizard tạo sản phẩm và các UI khác.

Lấy từ Shopee qua `GET /api/v2/product/get_category` (~vài ngàn entries/lần).
"""
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..services import shopee_product_api

_logger = logging.getLogger(__name__)


class ShopeeCategory(models.Model):
    _name = 'shopee.category'
    _description = 'Danh mục Shopee'
    _order = 'shop_id, display_name'
    _rec_name = 'display_name'

    shop_id = fields.Many2one(
        'shopee.shop', required=True, ondelete='cascade', index=True,
    )
    category_id = fields.Integer(string='Category ID', required=True, index=True)
    parent_category_id = fields.Integer(string='Parent Category ID', index=True)
    original_name = fields.Char(string='Tên gốc')
    display_name = fields.Char(string='Tên hiển thị', required=True)
    has_children = fields.Boolean(string='Có danh mục con')
    full_path = fields.Char(
        string='Đường dẫn đầy đủ',
        compute='_compute_full_path', store=True,
        help='Hiển thị dạng "Cha > Con > Cháu" để dễ tìm.',
    )
    last_synced = fields.Datetime(string='Đồng bộ lần cuối')

    _sql_constraints = [
        ('uniq_shop_cat', 'unique(shop_id, category_id)',
         'Danh mục đã tồn tại cho shop này.'),
    ]

    @api.depends('display_name', 'parent_category_id', 'shop_id')
    def _compute_full_path(self):
        # Build map per shop để tránh N+1 truy vấn
        cache = {}
        for rec in self:
            if not rec.shop_id:
                rec.full_path = rec.display_name or ''
                continue
            shop_key = rec.shop_id.id
            if shop_key not in cache:
                all_cats = self.search([('shop_id', '=', shop_key)])
                cache[shop_key] = {c.category_id: c for c in all_cats}
            cat_map = cache[shop_key]
            path = []
            cur = rec
            seen = set()
            while cur and cur.category_id not in seen:
                seen.add(cur.category_id)
                path.append(cur.display_name or cur.original_name or '?')
                parent = cat_map.get(cur.parent_category_id) if cur.parent_category_id else None
                if not parent or parent == cur:
                    break
                cur = parent
            rec.full_path = ' > '.join(reversed(path)) if path else (rec.display_name or '')

    @api.model
    def _sync_from_shopee(self, shop, language='vi'):
        """Đồng bộ toàn bộ cây danh mục cho 1 shop. Trả về số record upsert."""
        self = self.sudo()
        from odoo.addons.shopee_order_fetch.services.shopee_api import (
            get_credentials_from_shop,
        )
        if not shop:
            raise UserError(_('Vui lòng chỉ định shop.'))
        creds = get_credentials_from_shop(shop)
        cat_list = shopee_product_api.call_get_category(creds, language=language)
        if not cat_list:
            return 0
        now = fields.Datetime.now()
        existing = self.search([('shop_id', '=', shop.id)])
        by_cat = {c.category_id: c for c in existing}
        to_create = []
        upserted = 0
        for c in cat_list:
            cid = c.get('category_id')
            if not cid:
                continue
            vals = {
                'shop_id': shop.id,
                'category_id': cid,
                'parent_category_id': c.get('parent_category_id') or 0,
                'original_name': c.get('original_category_name') or '',
                'display_name': (
                    c.get('display_category_name')
                    or c.get('original_category_name')
                    or str(cid)
                ),
                'has_children': bool(c.get('has_children')),
                'last_synced': now,
            }
            rec = by_cat.get(cid)
            if rec:
                rec.write(vals)
            else:
                to_create.append(vals)
            upserted += 1
        if to_create:
            self.create(to_create)
        _logger.info(
            "Shopee category sync: shop=%s upserted=%d (api=%d)",
            shop.display_name, upserted, len(cat_list),
        )
        # Trigger compute lại full_path
        self.search([('shop_id', '=', shop.id)])._compute_full_path()
        return upserted

    def name_get(self):
        return [(r.id, r.full_path or r.display_name or str(r.category_id)) for r in self]

    @api.model
    def _name_search(self, name='', args=None, operator='ilike', limit=100, order=None):
        args = args or []
        domain = args
        if name:
            domain = [
                '|', '|',
                ('display_name', operator, name),
                ('original_name', operator, name),
                ('full_path', operator, name),
            ] + args
        return self._search(domain, limit=limit, order=order)
