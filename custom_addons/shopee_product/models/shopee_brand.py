# -*- coding: utf-8 -*-
"""Shopee brand cache per shop/category."""
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..services import shopee_product_api

_logger = logging.getLogger(__name__)


class ShopeeBrand(models.Model):
    _name = 'shopee.brand'
    _description = 'Thương hiệu Shopee'
    _order = 'shop_id, category_id, brand_name'
    _rec_name = 'brand_name'

    shop_id = fields.Many2one('shopee.shop', required=True, ondelete='cascade', index=True)
    category_id = fields.Integer(string='Category ID', required=True, index=True)
    brand_id = fields.Integer(string='Brand ID', required=True, index=True)
    brand_name = fields.Char(string='Tên thương hiệu', required=True, index=True)
    brand_logo = fields.Char(string='Logo URL')
    last_synced = fields.Datetime(string='Đồng bộ lần cuối')

    _sql_constraints = [
        ('uniq_shop_category_brand', 'unique(shop_id, category_id, brand_id)',
         'Brand đã tồn tại cho shop/category này.'),
    ]

    @api.model
    def _sync_from_shopee(self, shop, category_id):
        self = self.sudo()
        from odoo.addons.shopee_order_fetch.services.shopee_api import get_credentials_from_shop
        if not shop or not category_id:
            raise UserError(_('Vui lòng chọn shop và danh mục trước.'))
        creds = get_credentials_from_shop(shop)
        now = fields.Datetime.now()
        offset = 0
        page_size = 100
        all_brands = []
        while True:
            brands, has_next, next_offset = shopee_product_api.call_get_brand_list(
                creds, category_id, status=1, offset=offset, page_size=page_size,
            )
            all_brands.extend(brands or [])
            if not has_next:
                break
            offset = next_offset or (offset + page_size)

        if not any(int(b.get('brand_id') or 0) == 0 for b in all_brands):
            all_brands.insert(0, {'brand_id': 0, 'original_brand_name': 'No Brand'})

        existing = self.search([('shop_id', '=', shop.id), ('category_id', '=', int(category_id))])
        by_brand_id = {b.brand_id: b for b in existing}
        to_create = []
        upserted = 0
        for brand in all_brands:
            brand_id = int(brand.get('brand_id') or 0)
            vals = {
                'shop_id': shop.id,
                'category_id': int(category_id),
                'brand_id': brand_id,
                'brand_name': (
                    brand.get('original_brand_name')
                    or brand.get('display_brand_name')
                    or brand.get('brand_name')
                    or ('No Brand' if brand_id == 0 else str(brand_id))
                ),
                'brand_logo': brand.get('brand_logo') or '',
                'last_synced': now,
            }
            rec = by_brand_id.get(brand_id)
            if rec:
                rec.write(vals)
            else:
                to_create.append(vals)
            upserted += 1
        if to_create:
            self.create(to_create)
        _logger.info('Shopee brand sync: shop=%s category=%s upserted=%s', shop.display_name, category_id, upserted)
        return upserted
