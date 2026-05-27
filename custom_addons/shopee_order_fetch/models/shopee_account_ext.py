# -*- coding: utf-8 -*-
"""
Mở rộng shopee.shop để thêm cấu hình môi trường (sandbox / production).
"""
from odoo import fields, models


class ShopeeShopEnv(models.Model):
    _inherit = 'shopee.shop'

    is_sandbox = fields.Boolean(
        string='Môi trường Sandbox',
        default=False,
        help=(
            'Bật để gọi Shopee Sandbox API '
            '(https://openplatform.sandbox.test-stable.shopee.sg).\n'
            'Tắt để gọi Production API '
            '(https://partner.shopeemobile.com).'
        ),
    )
