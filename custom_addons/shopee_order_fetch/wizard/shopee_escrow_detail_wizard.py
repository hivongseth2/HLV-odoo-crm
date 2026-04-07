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
                return "{:,.0f}".format(val).replace(',', '.') + ' đ'
            return str(val) if val is not None else ''

        import json

        key_map = {
            'buyer_total_amount': 'Tổng tiền khách trả',
            'shipping_fee': 'Phí vận chuyển khách trả',
            'shopee_voucher': 'Voucher Shopee áp dụng',
            'seller_voucher': 'Voucher Shop áp dụng',
            'cost_of_goods_sold': 'Tiền gốc (Cost of goods sold)',
            'commission_fee': 'Phí hoa hồng (Commission Fee)',
            'service_fee': 'Phí dịch vụ (Service Fee)',
            'seller_transaction_fee': 'Phí giao dịch (Transaction Fee)',
            'actual_shipping_fee': 'Phí vận chuyển thực tế (Actual Shipping Fee)',
            'shopee_shipping_rebate': 'Shopee hỗ trợ phí VC (Shipping Rebate)',
            'seller_discount': 'Shop tài trợ khuyến mãi (Seller Discount)',
            'voucher_from_seller': 'Shop tài trợ khuyến mãi (Voucher)',
            'escrow_amount': 'TỔNG THU NHẬP DỰ KIẾN (Escrow Amount)',
            'buyer_payment_info': 'Thông tin Người mua (Buyer)',
            'order_income': 'Chi tiết Thu nhập của Shop (Order Income)',
            'order_sn': 'Mã đơn hàng (Order SN)',
        }

        # Some values need +/- prepended
        danger_keys = ['commission_fee', 'service_fee', 'seller_transaction_fee', 'actual_shipping_fee', 'seller_discount', 'voucher_from_seller']
        success_keys = ['shopee_shipping_rebate']

        html = '<table class="table table-bordered table-sm" style="width: 100%; margin-bottom: 0;">'

        def render_section(data_dict, title):
            if not data_dict:
                return ""
            res = f'''<thead class="bg-light">
                <tr><th colspan="2" style="font-size: 1.1em; color: #333; padding-top: 15px;">{title}</th></tr>
            </thead>
            <tbody>'''
            
            for k, v in data_dict.items():
                name = key_map.get(k, k)
                color_class = ""
                v_str = ""
                
                if isinstance(v, (dict, list)):
                    v_str = json.dumps(v, ensure_ascii=False)
                else:
                    v_str = f_vnd(v)
                    
                # Format special amounts if they are numbers
                is_num = isinstance(v, (int, float)) and v > 0
                if k == 'escrow_amount':
                    res += f'''<tr class="table-success" style="background-color: #d4edda; font-size: 1.2em;">
                        <td><b>{name}</b></td>
                        <td class="text-end" style="color: #155724;"><b>{v_str}</b></td>
                    </tr>'''
                    continue
                elif k in danger_keys and is_num:
                    v_str = f"-{v_str}" if '-' not in v_str else v_str
                    color_class = "text-danger"
                elif k in success_keys and is_num:
                    v_str = f"+{v_str}" if '+' not in v_str else v_str
                    color_class = "text-success"
                
                res += f'<tr><td>{name}</td><td class="text-end {color_class}">{v_str}</td></tr>'

            res += '</tbody>'
            return res

        # Separate main sections
        buyer_payment = escrow_data.get('buyer_payment_info', {})
        order_income = escrow_data.get('order_income', {})
        other_data = {k: v for k, v in escrow_data.items() if k not in ['buyer_payment_info', 'order_income']}

        # Render explicit sections first if they exist
        if buyer_payment:
            html += render_section(buyer_payment, f"1. {key_map['buyer_payment_info']}")
        if order_income:
            html += render_section(order_income, f"2. {key_map['order_income']}")

        # Render others
        if other_data:
            dict_other = {k: v for k, v in other_data.items() if isinstance(v, dict)}
            scalar_other = {k: v for k, v in other_data.items() if not isinstance(v, dict)}
            
            section_index = 3
            if scalar_other:
                html += render_section(scalar_other, f"{section_index}. Thông tin chung (Other Info)")
                section_index += 1
                
            for k, v in dict_other.items():
                title = f"{section_index}. {key_map.get(k, k.replace('_', ' ').title())}"
                html += render_section(v, title)
                section_index += 1

        html += '</table>'
        return html
