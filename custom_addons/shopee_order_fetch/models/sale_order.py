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
        if not escrow_data:
            return ""

        def f_vnd(val):
            if isinstance(val, (int, float)):
                if abs(val) >= 100 or val == 0:
                    return "{:,.0f}".format(val).replace(',', '.') + ' đ'
                return str(val)
            return str(val) if val is not None else ''

        key_map = {
            'buyer_total_amount': 'Tổng tiền khách trả (Buyer Total)',
            'shipping_fee': 'Phí vận chuyển khách trả',
            'shopee_voucher': 'Voucher Shopee (Buyer)',
            'seller_voucher': 'Voucher Shop (Buyer)',
            'buyer_payment_method': 'Phương thức thanh toán',
            'merchant_subtotal': 'Tổng tiền hàng (Subtotal)',
            'cost_of_goods_sold': 'Giá trị đơn hàng (COGS/Selling Price)',
            'commission_fee': 'Phí hoa hồng (Commission)',
            'service_fee': 'Phí dịch vụ (Service Fee)',
            'seller_transaction_fee': 'Phí giao dịch (Transaction Fee)',
            'actual_shipping_fee': 'Phí vận chuyển thực tế',
            'shopee_shipping_rebate': 'Shopee hỗ trợ phí VC',
            'seller_discount': 'Giảm giá từ Shop (Seller Discount)',
            'voucher_from_seller': 'Voucher từ Shop (Seller Voucher)',
            'escrow_amount': 'THỰC NHẬN (Escrow Amount)',
            'buyer_payment_info': '1. THÔNG TIN NGƯỜI MUA (BUYER PAYMENT)',
            'order_income': '2. CHI TIẾT THU NHẬP (ORDER INCOME)',
        }

        # List of keys to strictly ignore (non-price related)
        ignore_keys = ['items', 'tenure_info_list', 'error', 'message', 'request_id', 'return_order_sn_list', 'buyer_user_name', 'order_sn']

        html = f"""
        <details style="border: 1px solid #ddd; border-radius: 4px; padding: 10px; margin-top: 10px; background: #fafafa; width: 100%;">
            <summary style="cursor: pointer; color: #017e84; font-weight: bold; list-style: none; outline: none; margin-bottom: 0;">
                <i class="fa fa-caret-down pe-2"></i> Chi tiết phí &amp; chiết khấu Shopee (Escrow)
            </summary>
            <div style="margin-top: 15px;">
                <table class="table table-bordered table-sm" style="width: 100%; margin-bottom: 0; background: #fff;">
        """

        def render_dict_to_rows(data_dict, title):
            if not data_dict:
                return ""
            
            # Filter criteria: 
            # 1. Not in ignore_keys
            # 2. Not a dictionary or list
            # 3. Not equal to 0 (for numbers) and not empty
            filtered_data = {
                k: v for k, v in data_dict.items() 
                if k not in ignore_keys 
                and not isinstance(v, (dict, list)) 
                and v != 0 and v != 0.0 and v != ""
            }
            
            if not filtered_data:
                return ""

            res = f'''<thead class="bg-light">
                <tr><th colspan="2" style="font-size: 1.05em; color: #333; padding-top: 10px;">{title}</th></tr>
            </thead>
            <tbody>'''
            
            sorted_keys = sorted(filtered_data.keys(), key=lambda x: x not in ['escrow_amount', 'buyer_total_amount', 'cost_of_goods_sold'])
            for k in sorted_keys:
                v = filtered_data[k]
                name = key_map.get(k, k)
                v_str = f_vnd(v)
                
                row_style = ""
                val_style = ""
                if k in ['escrow_amount', 'buyer_total_amount']:
                    row_style = 'style="background-color: #f8f9fa; font-weight: bold;"'
                    val_style = 'style="color: #28a745; font-size: 1.1em;"' if k == 'escrow_amount' else ""

                res += f'<tr {row_style}><td>{name}</td><td class="text-end" {val_style}>{v_str}</td></tr>'
            res += '</tbody>'
            return res

        buyer_info = escrow_data.get('buyer_payment_info', {})
        if buyer_info:
            html += render_dict_to_rows(buyer_info, key_map.get('buyer_payment_info', '1. Buyer Info'))

        income_info = escrow_data.get('order_income', {})
        if income_info:
            html += render_dict_to_rows(income_info, key_map.get('order_income', '2. Order Income'))

        root_fields = {k: v for k, v in escrow_data.items() if k not in ['buyer_payment_info', 'order_income'] and k not in ignore_keys}
        if root_fields:
            html += render_dict_to_rows(root_fields, "3. THÔNG TIN KHÁC (OTHERS)")

        html += "</table></div></details>"
        return html
