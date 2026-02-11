# -*- coding: utf-8 -*-
from odoo import models, fields, api
import unicodedata


class ProductAlias(models.Model):
    _name = 'product.alias'
    _description = 'Product Alias'
    _rec_name = 'alias'
    _order = 'weight desc, alias asc'

    alias = fields.Char(string='Alias', required=True, index=True)
    product_id = fields.Many2one('product.template', string='Product', required=True, ondelete='cascade')
    weight = fields.Integer(string='Weight', default=10)
    active = fields.Boolean(default=True)
    normalized_alias = fields.Char(string='Normalized', index=True, readonly=True)

    _sql_constraints = [
        ('alias_unique', 'unique(alias, product_id)', 'Alias đã tồn tại cho sản phẩm này.'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            alias = vals.get('alias') or ''
            vals['normalized_alias'] = self._normalize(alias)
        return super().create(vals_list)

    def write(self, vals):
        if 'alias' in vals:
            vals['normalized_alias'] = self._normalize(vals.get('alias') or '')
        return super().write(vals)

    @api.model
    def _normalize(self, text):
        text = (text or '').strip().lower()
        text = unicodedata.normalize('NFKD', text)
        text = ''.join([c for c in text if not unicodedata.combining(c)])
        return text
