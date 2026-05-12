# -*- coding: utf-8 -*-
from odoo import fields, models


class AmisShopeeCustomerMap(models.Model):
    _name = 'amis.shopee.customer.map'
    _description = 'Map Shop Shopee → Tên khách hàng MISA'
    _order = 'sequence, id'

    config_id = fields.Many2one(
        'amis.callback.config',
        string='Cấu hình',
        required=True,
        ondelete='cascade',
    )
    sequence = fields.Integer(string='STT', default=10)
    shop_identifier = fields.Char(
        string='Shop Identifier',
        required=True,
        help='shop_identifier của shopee.shop (số ID shop Shopee). VD: 796817584',
    )
    shop_name = fields.Char(
        string='Tên shop (ghi chú)',
        help='Tên shop để dễ nhận biết. Không ảnh hưởng logic.',
    )
    customer_name = fields.Char(
        string='Tên khách hàng MISA',
        required=True,
        help='Tên hiển thị trong cột "Tên khách hàng" khi xuất MISA. '
             'VD: KHÁCH HÀNG KHÔNG CUNG CẤP THÔNG TIN_SHOPEE MILWAUKEE',
    )
    customer_code = fields.Char(
        string='Mã khách hàng MISA',
        help='Mã đối tượng trong MISA (nếu có). Điền để fill cột "Mã khách hàng".',
    )
