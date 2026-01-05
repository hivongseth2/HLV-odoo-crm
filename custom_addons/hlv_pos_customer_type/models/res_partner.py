# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ResPartner(models.Model):
    _inherit = 'res.partner'

    pos_customer_type = fields.Many2one(
        'pos.customer.type',
        string='Loại khách hàng',
        ondelete='set null',
    )

    @api.model
    def _load_pos_data_fields(self, config_id):
        params = super()._load_pos_data_fields(config_id)
        params.append('pos_customer_type')
        return params

    @api.model
    def _load_pos_data_domain(self, data):
        domain = super()._load_pos_data_domain(data)
        domain = domain or []
        domain.append(('type', '!=', 'delivery'))
        return domain
