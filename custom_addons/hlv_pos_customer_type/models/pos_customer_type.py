# -*- coding: utf-8 -*-
from odoo import models, fields, api


class PosCustomerType(models.Model):
    _name = 'pos.customer.type'
    _description = 'POS Customer Type'
    _order = 'sequence, id'

    name = fields.Char(string='Tên loại khách hàng', required=True, translate=True)
    code = fields.Char(string='Mã', help='Mã dùng để nhận diện')
    color = fields.Char(string='Màu badge', default='info', 
                        help='CSS class cho badge: info, warning, success, danger, primary, secondary')
    sequence = fields.Integer(string='Thứ tự', default=10)
    active = fields.Boolean(string='Active', default=True)

    @api.model
    def _load_pos_data_domain(self, data):
        return [('active', '=', True)]

    @api.model
    def _load_pos_data_fields(self, config_id):
        return ['id', 'name', 'code', 'color', 'sequence']
