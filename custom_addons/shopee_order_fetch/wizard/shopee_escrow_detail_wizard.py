# -*- coding: utf-8 -*-
from odoo import models, fields, api

class ShopeeEscrowDetailWizard(models.TransientModel):
    _name = 'shopee.escrow.detail.wizard'
    _description = 'Chi tiết Escrow Shopee'

    order_id = fields.Many2one('sale.order', string='Đơn hàng', readonly=True)
    escrow_html = fields.Html(string='Chi tiết Escrow', readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self.env.context.get('active_id')
        if active_id and self.env.context.get('active_model') == 'sale.order':
            order = self.env['sale.order'].browse(active_id)
            res['order_id'] = order.id
            res['escrow_html'] = self._build_escrow_html(order.shopee_escrow_data)
        return res

    def _build_escrow_html(self, escrow_data):
        if not escrow_data:
            return "<p>Lỗi không tìm thấy dữ liệu Escrow trên đơn hàng. Vui lòng bấm 'Cập nhật giá Shopee' để lấy dữ liệu về.</p>"

        order_income = escrow_data.get('order_income', {})
        buyer_payment = escrow_data.get('buyer_payment_info', {})

        def f_vnd(val):
            return "{:,.0f}".format(val or 0).replace(',', '.')

        html = f"""
        <table class="table table-bordered table-sm" style="width: 100%; margin-bottom: 0;">
            <thead class="bg-light">
                <tr><th colspan="2" style="font-size: 1.1em; color: #333;">1. Thông tin Người mua (Buyer)</th></tr>
            </thead>
            <tbody>
                <tr><td>Tổng tiền khách trả</td><td class="text-end"><b>{f_vnd(buyer_payment.get('buyer_total_amount'))} đ</b></td></tr>
                <tr><td>Phí vận chuyển khách trả</td><td class="text-end">{f_vnd(buyer_payment.get('shipping_fee'))} đ</td></tr>
                <tr><td>Voucher Shopee áp dụng</td><td class="text-end text-danger">{f_vnd(buyer_payment.get('shopee_voucher'))} đ</td></tr>
                <tr><td>Voucher Shop áp dụng</td><td class="text-end text-danger">{f_vnd(buyer_payment.get('seller_voucher'))} đ</td></tr>
            </tbody>
            <thead class="bg-light">
                <tr><th colspan="2" style="font-size: 1.1em; color: #333; padding-top: 15px;">2. Chi tiết Thu nhập của Shop (Order Income)</th></tr>
            </thead>
            <tbody>
                <tr><td>Tiền gốc (Cost of goods sold)</td><td class="text-end">{f_vnd(order_income.get('cost_of_goods_sold'))} đ</td></tr>
                <tr><td>Phí hoa hồng (Commission Fee)</td><td class="text-end text-danger">-{f_vnd(order_income.get('commission_fee'))} đ</td></tr>
                <tr><td>Phí dịch vụ (Service Fee)</td><td class="text-end text-danger">-{f_vnd(order_income.get('service_fee'))} đ</td></tr>
                <tr><td>Phí giao dịch (Transaction Fee)</td><td class="text-end text-danger">-{f_vnd(order_income.get('seller_transaction_fee'))} đ</td></tr>
                <tr><td>Phí vận chuyển thực tế (Actual Shipping Fee)</td><td class="text-end text-danger">-{f_vnd(order_income.get('actual_shipping_fee'))} đ</td></tr>
                <tr><td>Shopee hỗ trợ phí VC (Shipping Rebate)</td><td class="text-end text-success">+{f_vnd(order_income.get('shopee_shipping_rebate'))} đ</td></tr>
                <tr><td>Shop tài trợ khuyến mãi (Seller Discount / Voucher)</td><td class="text-end text-danger">-{f_vnd(order_income.get('seller_discount') + order_income.get('voucher_from_seller', 0))} đ</td></tr>
                <tr class="table-success" style="background-color: #d4edda; font-size: 1.2em;">
                    <td><b>TỔNG THU NHẬP DỰ KIẾN (Escrow Amount)</b></td>
                    <td class="text-end" style="color: #155724;"><b>{f_vnd(order_income.get('escrow_amount'))} đ</b></td>
                </tr>
            </tbody>
        </table>
        """
        return html
