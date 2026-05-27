# -*- coding: utf-8 -*-
"""
Mở rộng shopee.account để thêm cấu hình môi trường (sandbox / production).
"""
from odoo import fields, models

SHOPEE_PROD_URL     = 'https://partner.shopeemobile.com'
SHOPEE_SANDBOX_URL  = 'https://openplatform.sandbox.test-stable.shopee.sg'


class ShopeeAccountEnv(models.Model):
    _inherit = 'shopee.account'

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

    shopee_env_base_url = fields.Char(
        string='Base URL',
        compute='_compute_shopee_env_base_url',
    )

    def _compute_shopee_env_base_url(self):
        for rec in self:
            rec.shopee_env_base_url = (
                SHOPEE_SANDBOX_URL if rec.is_sandbox else SHOPEE_PROD_URL
            )
