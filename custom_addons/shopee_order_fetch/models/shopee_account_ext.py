# -*- coding: utf-8 -*-
"""
Mở rộng shopee.shop để thêm cấu hình môi trường (sandbox / production)
và hỗ trợ làm mới access_token.
"""
from odoo import fields, models, _
from odoo.exceptions import UserError


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

    # ── Token helpers ────────────────────────────────────

    def _refresh_shopee_token(self):
        """
        Làm mới access_token của shop này bằng cách gọi Shopee refresh token API.
        Được gọi tự động khi API trả về invalid_access_token.
        Trả về new_access_token.
        """
        self.ensure_one()
        from odoo.addons.shopee_order_fetch.services.shopee_api import (
            refresh_shopee_access_token,
        )
        return refresh_shopee_access_token(self)

    def action_refresh_shopee_token(self):
        """Nút thủ công: làm mới Shopee access_token."""
        self.ensure_one()
        try:
            self._refresh_shopee_token()
        except UserError:
            raise
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Token Shopee đã được làm mới'),
                'message': _("access_token của shop '%s' đã được cập nhật thành công.") % self.display_name,
                'type': 'success',
                'sticky': False,
            },
        }

