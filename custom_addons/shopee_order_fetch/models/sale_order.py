# -*- coding: utf-8 -*-
"""
models/sale_order.py

Mở rộng sale.order để thêm nút "Cập nhật giá Shopee" trực tiếp trên form đơn hàng.
Toàn bộ logic gọi API và xử lý escrow được ủy thác cho services/.
"""
import logging
import json

from odoo import models, fields, api, _
from odoo.exceptions import UserError

from ..services import shopee_api, shopee_escrow, shopee_order_builder

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    shopee_escrow_data = fields.Json(
        string='Dữ liệu Escrow Shopee',
        readonly=True,
        help="Lưu trữ toàn bộ JSON trả về từ API Escrow của Shopee để kiểm tra chi tiết các khoản phí/chiết khấu."
    )

    def action_update_price_from_escrow(self):
        """Gọi Shopee API get_escrow_detail để cập nhật lại giá cho đơn hàng hiện tại."""
        for order in self:
            if not order.shopee_order_ref:
                raise UserError(
                    _("Đơn hàng '%s' không có mã tham chiếu Shopee (shopee_order_ref).")
                    % order.name
                )
            if not order.shopee_shop_id:
                raise UserError(
                    _("Đơn hàng '%s' chưa được liên kết với Shop Shopee.") % order.name
                )

            creds = shopee_api.get_credentials_from_shop(order.shopee_shop_id)
            escrow_data = shopee_api.call_escrow_detail_strict(creds, order.shopee_order_ref)

            if escrow_data.get('order_income', {}).get('items'):
                shopee_escrow.update_order_lines_from_escrow(order, escrow_data)

            shopee_escrow.apply_escrow_voucher(order, escrow_data)
            
            if escrow_data:
                order.shopee_escrow_data = escrow_data

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Cập nhật giá Shopee"),
                'message': _("Đã cập nhật giá từ Escrow thành công cho %d đơn hàng.") % len(self),
                'type': 'success',
                'sticky': False,
            },
        }

    shopee_escrow_html = fields.Html(
        string="Chi tiết Escrow HTML",
        compute="_compute_shopee_escrow_html",
        store=False,
        sanitize=False
    )

    @api.depends('shopee_escrow_data')
    def _compute_shopee_escrow_html(self):
        for order in self:
            if not order.shopee_escrow_data:
                order.shopee_escrow_html = False
                continue
            order.shopee_escrow_html = self._build_raw_escrow_html(order.shopee_escrow_data)

    def _build_raw_escrow_html(self, escrow_data):
        return shopee_escrow.build_escrow_html_common(escrow_data, is_wizard=False)
