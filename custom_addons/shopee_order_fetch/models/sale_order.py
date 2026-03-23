# -*- coding: utf-8 -*-
"""
models/sale_order.py

Mở rộng sale.order để thêm nút "Cập nhật giá Shopee" trực tiếp trên form đơn hàng.
Toàn bộ logic gọi API và xử lý escrow được ủy thác cho services/.
"""
import logging

from odoo import models, fields, _
from odoo.exceptions import UserError

from ..services import shopee_api, shopee_escrow

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

    def _compute_shopee_escrow_html(self):
        for order in self:
            if not order.shopee_escrow_data:
                order.shopee_escrow_html = False
                continue

            escrow_data = order.shopee_escrow_data
            order_income = escrow_data.get('order_income', {})
            buyer_payment = escrow_data.get('buyer_payment_info', {})

            def f_vnd(val):
                return "{:,.0f}".format(val or 0).replace(',', '.')

            seller_discount_total = order_income.get('seller_discount', 0) + order_income.get('voucher_from_seller', 0)
            
            html = f"""
            <details style="border: 1px solid #ddd; border-radius: 4px; padding: 10px; margin-top: 10px; background: #fafafa; width: 100%;">
                <summary style="cursor: pointer; color: #017e84; font-weight: bold; list-style: none; outline: none; margin-bottom: 0;">
                    <i class="fa fa-caret-down pe-2"></i> Chi tiết phí &amp; chiết khấu Shopee (Escrow)
                </summary>
                <div style="margin-top: 15px;">
                    <table class="table table-bordered table-sm" style="width: 100%; margin-bottom: 0; background: #fff;">
                        <thead class="bg-light">
                            <tr><th colspan="2" style="font-size: 1.05em; color: #333;">1. Thông tin Người mua (Buyer)</th></tr>
                        </thead>
                        <tbody>
                            <tr><td>Tổng tiền khách trả</td><td class="text-end"><b>{f_vnd(buyer_payment.get('buyer_total_amount'))} đ</b></td></tr>
                            <tr><td>Phí vận chuyển khách trả</td><td class="text-end">{f_vnd(buyer_payment.get('shipping_fee'))} đ</td></tr>
                            <tr><td>Voucher Shopee áp dụng</td><td class="text-end text-danger">{f_vnd(buyer_payment.get('shopee_voucher'))} đ</td></tr>
                            <tr><td>Voucher Shop áp dụng</td><td class="text-end text-danger">{f_vnd(buyer_payment.get('seller_voucher'))} đ</td></tr>
                        </tbody>
                        <thead class="bg-light">
                            <tr><th colspan="2" style="font-size: 1.05em; color: #333; padding-top: 12px;">2. Chi tiết Thu nhập của Shop (Order Income)</th></tr>
                        </thead>
                        <tbody>
                            <tr><td>Tiền gốc (Cost of goods sold)</td><td class="text-end">{f_vnd(order_income.get('cost_of_goods_sold'))} đ</td></tr>
                            <tr><td>Phí hoa hồng (Commission Fee)</td><td class="text-end text-danger">-{f_vnd(order_income.get('commission_fee'))} đ</td></tr>
                            <tr><td>Phí dịch vụ (Service Fee)</td><td class="text-end text-danger">-{f_vnd(order_income.get('service_fee'))} đ</td></tr>
                            <tr><td>Phí giao dịch (Transaction Fee)</td><td class="text-end text-danger">-{f_vnd(order_income.get('seller_transaction_fee'))} đ</td></tr>
                            <tr><td>Phí vận chuyển thực tế (Actual Shipping Fee)</td><td class="text-end text-danger">-{f_vnd(order_income.get('actual_shipping_fee'))} đ</td></tr>
                            <tr><td>Shopee hỗ trợ phí VC (Shipping Rebate)</td><td class="text-end text-success">+{f_vnd(order_income.get('shopee_shipping_rebate'))} đ</td></tr>
                            <tr><td>Shop tài trợ khuyến mãi (Seller Discount / Voucher)</td><td class="text-end text-danger">-{f_vnd(seller_discount_total)} đ</td></tr>
                            <tr class="table-success" style="background-color: #d4edda; font-size: 1.1em;">
                                <td><b>TỔNG THU NHẬP DỰ KIẾN (Escrow Amount)</b></td>
                                <td class="text-end" style="color: #155724;"><b>{f_vnd(order_income.get('escrow_amount'))} đ</b></td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </details>
            """
            order.shopee_escrow_html = html
