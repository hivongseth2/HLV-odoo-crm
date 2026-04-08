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
            # 1. Buyer Payment Information
            'buyer_total_amount': 'Tổng tiền khách trả (Buyer Total)',
            'shipping_fee': 'Phí vận chuyển khách trả',
            'shopee_voucher': 'Voucher Shopee (Buyer)',
            'seller_voucher': 'Voucher Shop (Buyer)',
            'buyer_payment_method': 'Phương thức thanh toán',
            'merchant_subtotal': 'Tổng tiền hàng (Subtotal)',
            'bulky_handling_fee': 'Phí xử lý hàng cồng kềnh',
            'buyer_paid_extended_warranty': 'Khách trả bảo hành mở rộng',
            'buyer_paid_installation_fee': 'Phí lắp đặt khách trả',
            'buyer_service_fee': 'Phí dịch vụ khách trả',
            'buyer_tax_amount': 'Thuế khách trả',
            'credit_card_promotion': 'Khuyến mãi thẻ tín dụng',
            'discount_pix': 'Giảm giá Pix',
            'footwear_tax': 'Thuế giày dép',
            'icms_tax_amount': 'Thuế ICMS',
            'import_duty_and_excise_tax': 'Thuế nhập khẩu và tiêu thụ đặc biệt',
            'import_processing_charge': 'Phí xử lý nhập khẩu',
            'import_tax_amount': 'Thuế nhập khẩu',
            'initial_buyer_txn_fee': 'Phí giao dịch ban đầu của khách',
            'insurance_premium': 'Phí bảo hiểm',
            'iof_tax_amount': 'Thuế IOF',
            'lvg_sales_tax_adjustment': 'Điều chỉnh thuế bán hàng LVG',
            'shipping_fee_sst_amount': 'Thuế SST phí vận chuyển',
            'shopee_coins_redeemed': 'Shopee xu đã dùng',
            'total_tax_and_fees_amount': 'Tổng thuế và phí',
            'trade_in_bonus': 'Thưởng thu cũ đổi mới',
            'trade_in_discount': 'Giảm giá thu cũ đổi mới',
            'vat': 'Thuế GTGT (VAT)',

            # 2. Order Income Information
            'cost_of_goods_sold': 'Giá trị đơn hàng (COGS/Selling Price)',
            'commission_fee': 'Phí hoa hồng sàn (Commission Fee)',
            'service_fee': 'Phí dịch vụ (Service Fee)',
            'seller_transaction_fee': 'Phí giao dịch (Transaction Fee)',
            'actual_shipping_fee': 'Phí vận chuyển thực tế',
            'shopee_shipping_rebate': 'Shopee hỗ trợ phí VC',
            'seller_discount': 'Giảm giá từ Shop (Seller Discount)',
            'voucher_from_seller': 'Voucher từ Shop (Seller Voucher)',
            'escrow_amount': 'THỰC NHẬN (Escrow Amount)',
            'escrow_amount_after_adjustment': 'Thực nhận sau điều chỉnh',
            
            'actual_installation_fee': 'Phí lắp đặt thực tế',
            'ads_escrow_top_up_fee_or_technical_support_fee': 'Phí quảng cáo/hỗ trợ kỹ thuật',
            'campaign_fee': 'Phí tham gia chương trình (Campaign Fee)',
            'coins': 'Shopee Xu',
            'credit_card_transaction_fee': 'Phí giao dịch thẻ tín dụng',
            'cross_border_tax': 'Thuế xuyên biên giới',
            'delivery_seller_protection_fee_premium_amount': 'Phí bảo vệ người bán khi giao hàng',
            'drc_adjustable_refund': 'Hoàn tiền điều chỉnh DRC',
            'escrow_import_tax': 'Thuế nhập khẩu Escrow',
            'escrow_tax': 'Thuế Escrow',
            'fbs_fee': 'Phí FBS',
            'final_escrow_product_gst': 'Thuế GST sản phẩm cuối cùng',
            'final_escrow_shipping_gst': 'Thuế GST vận chuyển cuối cùng',
            'final_product_protection': 'Bảo vệ sản phẩm cuối cùng',
            'final_product_vat_tax': 'Thuế GTGT sản phẩm cuối cùng',
            'final_return_to_seller_shipping_fee': 'Phí vận chuyển trả hàng cuối cùng',
            'final_shipping_fee': 'Phí vận chuyển cuối cùng',
            'final_shipping_vat_tax': 'Thuế GTGT vận chuyển cuối cùng',
            'fsf_seller_protection_fee_claim_amount': 'Bồi thường bảo vệ người bán FSF',
            'installation_fee_paid_by_buyer': 'Phí lắp đặt người mua trả',
            'order_ams_commission_fee': 'Phí hoa hồng AMS',
            'order_chargeable_weight': 'Trọng lượng tính phí',
            'order_discounted_price': 'Giá sau giảm',
            'order_original_price': 'Giá gốc đơn hàng',
            'order_seller_discount': 'Tổng giảm giá từ người bán',
            'order_selling_price': 'Giá bán đơn hàng',
            'original_cost_of_goods_sold': 'Giá vốn hàng bán gốc',
            'overseas_return_service_fee': 'Phí dịch vụ trả hàng nước ngoài',
            'payment_promotion': 'Khuyến mãi thanh toán',
            'pix_discount': 'Giảm giá Pix (Seller)',
            'return_to_seller_shipping_fee_sst': 'Thuế SST phí chuyển trả hàng',
            'reverse_shipping_fee': 'Phí vận chuyển ngược',
            'reverse_shipping_fee_sst': 'Thuế SST phí vận chuyển ngược',
            'rsf_seller_protection_fee_claim_amount': 'Bồi thường bảo vệ người bán RSF',
            'sales_tax_on_lvg': 'Thuế bán hàng trên LVG',
            'seller_coin_cash_back': 'Hoàn xu từ người bán',
            'seller_lost_compensation': 'Bồi thường hàng thất lạc',
            'seller_order_processing_fee': 'Phí xử lý đơn hàng của shop',
            'seller_return_refund': 'Hoàn tiền trả hàng',
            'seller_shipping_discount': 'Hỗ trợ phí VC từ shop',
            'shipping_fee_discount_from_3pl': 'Giảm phí VC từ ĐVVC',
            'shipping_fee_sst': 'Thuế SST phí vận chuyển (Income)',
            'shipping_seller_protection_fee_amount': 'Phí bảo vệ người bán (Vận chuyển)',
            'th_import_duty': 'Thuế nhập khẩu TH',
            'total_adjustment_amount': 'Tổng tiền điều chỉnh',
            'trade_in_bonus_by_seller': 'Thưởng thu cũ đổi mới từ shop',
            'vat_on_imported_goods': 'Thuế GTGT hàng nhập khẩu',
            'withholding_pit_tax': 'Thuế TNCN khấu trừ',
            'withholding_tax': 'Thuế khấu trừ',
            'withholding_vat_tax': 'Thuế GTGT khấu trừ',

            # Labels for sections
            'buyer_payment_info': '1. THÔNG TIN NGƯỜI MUA (BUYER PAYMENT)',
            'order_income': '2. CHI TIẾT THU NHẬP (ORDER INCOME)',
            'order_sn': 'Mã đơn hàng',
            'buyer_user_name': 'Tên người mua',
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
