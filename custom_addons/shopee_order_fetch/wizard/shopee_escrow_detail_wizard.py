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

        def f_vnd(val):
            if isinstance(val, (int, float)):
                # If absolute value > 100, format as money, otherwise keep as is
                if abs(val) >= 100 or val == 0:
                    return "{:,.0f}".format(val).replace(',', '.') + ' đ'
                return str(val)
            return str(val) if val is not None else ''

        import json

        key_map = {
            # Buyer section
            'buyer_total_amount': 'Tổng tiền khách trả (Buyer Total)',
            'shipping_fee': 'Phí vận chuyển khách trả',
            'shopee_voucher': 'Voucher Shopee (Buyer)',
            'seller_voucher': 'Voucher Shop (Buyer)',
            'buyer_payment_method': 'Phương thức thanh toán',
            'merchant_subtotal': 'Tổng tiền hàng (Subtotal)',
            # Order Income section
            'cost_of_goods_sold': 'Giá trị đơn hàng (COGS/Selling Price)',
            'commission_fee': 'Phí hoa hồng (Commission)',
            'service_fee': 'Phí dịch vụ (Service Fee)',
            'seller_transaction_fee': 'Phí giao dịch (Transaction Fee)',
            'actual_shipping_fee': 'Phí vận chuyển thực tế',
            'shopee_shipping_rebate': 'Shopee hỗ trợ phí VC',
            'seller_discount': 'Giảm giá từ Shop (Seller Discount)',
            'voucher_from_seller': 'Voucher từ Shop (Seller Voucher)',
            'escrow_amount': 'THỰC NHẬN (Escrow Amount)',
            'escrow_amount_after_adjustment': 'Thực nhận sau điều chỉnh',
            'order_sn': 'Mã đơn hàng',
            'buyer_user_name': 'Tên người mua',
            # Other labels for sections
            'buyer_payment_info': '1. THÔNG TIN NGƯỜI MUA (BUYER PAYMENT)',
            'order_income': '2. CHI TIẾT THU NHẬP (ORDER INCOME)',
        }

        # List of keys to strictly ignore
        ignore_keys = ['items', 'tenure_info_list', 'error', 'message', 'request_id', 'return_order_sn_list', 'buyer_user_name', 'order_sn']

        html = '<table class="table table-bordered table-sm" style="width: 100%; margin-bottom: 0;">'

        def render_dict_to_rows(data_dict, title):
            if not data_dict:
                return ""

            # Filter criterion: Hide if value is 0, 0.0 or empty string
            filtered_data = {
                k: v for k, v in data_dict.items() 
                if k not in ignore_keys 
                and not isinstance(v, (dict, list))
                and v != 0 and v != 0.0 and v != ""
            }
            
            if not filtered_data:
                return ""

            res = f'''<thead class="bg-light">
                <tr><th colspan="2" style="font-size: 1.1em; color: #333; padding-top: 10px; border-top: 2px solid #dee2e6;">{title}</th></tr>
            </thead>
            <tbody>'''
            
            sorted_keys = sorted(filtered_data.keys(), key=lambda x: x not in ['escrow_amount', 'buyer_total_amount', 'cost_of_goods_sold'])
            
            for k in sorted_keys:
                v = filtered_data[k]
                name = key_map.get(k, k)
                v_str = f_vnd(v)

                # Special styling for main results
                row_style = ""
                val_style = ""
                if k in ['escrow_amount', 'buyer_total_amount']:
                    row_style = 'style="background-color: #f8f9fa; font-weight: bold;"'
                    val_style = 'style="color: #28a745; font-size: 1.1em;"' if k == 'escrow_amount' else ""

                res += f'<tr {row_style}><td>{name}</td><td class="text-end" {val_style}>{v_str}</td></tr>'

            res += '</tbody>'
            return res

        # 1. Buyer Information
        buyer_info = escrow_data.get('buyer_payment_info', {})
        if buyer_info:
            html += render_dict_to_rows(buyer_info, key_map['buyer_payment_info'])

        # 2. Order Income
        income_info = escrow_data.get('order_income', {})
        if income_info:
            html += render_dict_to_rows(income_info, key_map['order_income'])

        # 3. Other fields at root level
        root_fields = {k: v for k, v in escrow_data.items() if k not in ['buyer_payment_info', 'order_income'] and k not in ignore_keys}
        if root_fields:
            html += render_dict_to_rows(root_fields, "3. THÔNG TIN KHÁC (OTHERS)")

        html += '</table>'
        return html
