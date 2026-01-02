# -*- coding: utf-8 -*-
from odoo import models, fields, api

class ResPartner(models.Model):
    _inherit = 'res.partner'

    pos_customer_type = fields.Selection([
        ('cash', 'Khách thanh toán tiền mặt'),
        ('bank', 'Khách thanh toán qua chuyển khoản'),
    ], string='Loại khách hàng')

    @api.model
    def _load_pos_data_fields(self, config_id):
        params = super()._load_pos_data_fields(config_id)
        params.append('pos_customer_type')
        return params
