# -*- coding: utf-8 -*-
from odoo import models, fields

class ZaloCustomerTag(models.Model):
    _name = 'zalo.customer.tag'
    _description = 'Zalo Customer Tag'

    name = fields.Char(string='Tên thẻ', required=True)
    color = fields.Integer(string='Màu sắc')
    category = fields.Selection([
        ('role', 'Vai trò'),      # Khách lẻ, NCC, Đại lý
        ('brand', 'Thương hiệu'), # Bosch, Makita
        ('need', 'Nhu cầu'),      # Mua hàng, Hỏi giá
        ('other', 'Khác')
    ], string='Phân loại', default='other', required=True)

    _sql_constraints = [
        ('name_uniq', 'unique (name)', "Tên thẻ phải là duy nhất!"),
    ]
