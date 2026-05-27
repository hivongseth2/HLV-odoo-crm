# -*- coding: utf-8 -*-
"""Shopee attribute/value cache per shop/category."""
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..services import shopee_product_api

_logger = logging.getLogger(__name__)


class ShopeeAttribute(models.Model):
    _name = 'shopee.attribute'
    _description = 'Thuộc tính Shopee'
    _order = 'shop_id, category_id, is_mandatory desc, attribute_name'
    _rec_name = 'attribute_name'

    shop_id = fields.Many2one('shopee.shop', required=True, ondelete='cascade', index=True)
    category_id = fields.Integer(string='Category ID', required=True, index=True)
    attribute_id = fields.Integer(string='Attribute ID', required=True, index=True)
    attribute_name = fields.Char(string='Tên thuộc tính', required=True, index=True)
    is_mandatory = fields.Boolean(string='Bắt buộc')
    input_type = fields.Char(string='Kiểu nhập')
    value_line_ids = fields.One2many('shopee.attribute.value', 'attribute_id_ref', string='Giá trị')
    last_synced = fields.Datetime(string='Đồng bộ lần cuối')

    _sql_constraints = [
        ('uniq_shop_category_attribute', 'unique(shop_id, category_id, attribute_id)',
         'Attribute đã tồn tại cho shop/category này.'),
    ]

    @api.model
    def _sync_from_shopee(self, shop, category_id, language='vi'):
        self = self.sudo()
        from odoo.addons.shopee_order_fetch.services.shopee_api import get_credentials_from_shop
        if not shop or not category_id:
            raise UserError(_('Vui lòng chọn shop và danh mục trước.'))
        creds = get_credentials_from_shop(shop)
        attrs = shopee_product_api.call_get_attribute_tree(creds, category_id, language=language)
        now = fields.Datetime.now()
        existing = self.search([('shop_id', '=', shop.id), ('category_id', '=', int(category_id))])
        by_attr_id = {a.attribute_id: a for a in existing}
        Value = self.env['shopee.attribute.value'].sudo()
        upserted = 0
        for attr in attrs or []:
            aid = int(attr.get('attribute_id') or 0)
            if not aid:
                continue
            name = attr.get('original_attribute_name') or attr.get('attribute_name') or str(aid)
            vals = {
                'shop_id': shop.id,
                'category_id': int(category_id),
                'attribute_id': aid,
                'attribute_name': name,
                'is_mandatory': bool(attr.get('is_mandatory')),
                'input_type': attr.get('input_type') or '',
                'last_synced': now,
            }
            rec = by_attr_id.get(aid)
            if rec:
                rec.write(vals)
            else:
                rec = self.create(vals)
                by_attr_id[aid] = rec
            values = attr.get('attribute_value_list') or attr.get('value_list') or []
            existing_values = Value.search([('attribute_id_ref', '=', rec.id)])
            by_value_id = {v.value_id: v for v in existing_values}
            for value in values:
                vid = int(value.get('value_id') or value.get('attribute_value_id') or 0)
                vname = (
                    value.get('original_value_name')
                    or value.get('value_name')
                    or value.get('display_value_name')
                    or str(vid)
                )
                vvals = {
                    'attribute_id_ref': rec.id,
                    'value_id': vid,
                    'value_name': vname,
                    'value_unit': value.get('value_unit') or '',
                }
                vrec = by_value_id.get(vid)
                if vrec:
                    vrec.write(vvals)
                else:
                    Value.create(vvals)
            upserted += 1
        _logger.info('Shopee attribute sync: shop=%s category=%s upserted=%s', shop.display_name, category_id, upserted)
        return upserted


class ShopeeAttributeValue(models.Model):
    _name = 'shopee.attribute.value'
    _description = 'Giá trị thuộc tính Shopee'
    _order = 'attribute_id_ref, value_name'
    _rec_name = 'value_name'

    attribute_id_ref = fields.Many2one('shopee.attribute', required=True, ondelete='cascade', index=True)
    value_id = fields.Integer(string='Value ID', required=True, index=True)
    value_name = fields.Char(string='Giá trị', required=True, index=True)
    value_unit = fields.Char(string='Đơn vị')

    _sql_constraints = [
        ('uniq_attribute_value', 'unique(attribute_id_ref, value_id)',
         'Giá trị đã tồn tại cho attribute này.'),
    ]
