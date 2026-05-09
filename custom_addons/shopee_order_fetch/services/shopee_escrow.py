# -*- coding: utf-8 -*-
"""
services/shopee_escrow.py

Xử lý dữ liệu Escrow từ Shopee: cập nhật giá theo items, áp dụng voucher.
Các hàm ở đây nhận `sale.order` record làm tham số và thực hiện write trực tiếp.
"""
import logging

_logger = logging.getLogger(__name__)


def get_tax_included(env, company, product=None):
    """
    Tìm thuế bán hàng có price_include=True trong công ty chỉ định.
    Nếu `product` được truyền vào, sẽ dựa trên `taxes_id` (Customer Taxes) của sản phẩm 
    để tìm thuế `price_include=True` có cùng VAT (%) amount.
    - Nếu sản phẩm KHÔNG CÓ thuế -> Bỏ trống thuế (return False).
    Trả về account.tax record hoặc False.
    """
    Tax = env['account.tax'].sudo()
    
    # 1. Tìm thuế Include dựa trên thuế đang cấu hình trên Sản phẩm
    if product:
        if not product.taxes_id:
            # Nếu sản phẩm không cấu hình thuế -> Không gán thuế cho dòng này
            return False
            
        # Lập domain tìm loại thuế có cùng mức % (amount) như thuế của sản phẩm
        tax_amount = product.taxes_id[0].amount
        tax = Tax.search([
            ('type_tax_use', '=', 'sale'),
            ('price_include', '=', True),
            ('amount', '=', tax_amount),
            ('company_id', '=', company.id),
        ], limit=1)
        
        if tax:
            return tax
        else:
            _logger.warning("Shopee: Sản phẩm '%s' chịu thuế %s%% nhưng không có cấu hình 'Thuế %s%% (Bao gồm)'. Bỏ trống thuế dòng này.", product.name, tax_amount, tax_amount)
            return False

    # 2. Rơi vào fallback (chỉ dùng khi gọi hàm mà KO TRUYỀN product)
    tax = Tax.search([
        ('type_tax_use', '=', 'sale'),
        ('price_include', '=', True),
        ('company_id', '=', company.id),
    ], limit=1)
    if tax:
        return tax

    # 3. Fallback cuối
    default_tax = company.account_sale_tax_id
    if default_tax:
        tax = Tax.search([
            ('type_tax_use', '=', 'sale'),
            ('price_include', '=', True),
            ('amount', '=', default_tax.amount),
            ('company_id', '=', company.id),
        ], limit=1)
        if tax:
            return tax

    return False


def _find_order_line_for_escrow_item(so, item_data):
    """
    Tìm sale.order.line phù hợp với 1 item trong escrow.

    Thứ tự ưu tiên:
    1. Khớp SKU chính xác (default_code == sku)
    2. Khớp SKU sau khi normalize (bỏ khoảng trắng, uppercase)
    3. Khớp qua bảng shopee.item (item_id + model_id)

    :return: sale.order.line recordset (có thể rỗng)
    """
    sku = item_data.get('model_sku', '') or item_data.get('item_sku', '')
    item_id = item_data.get('item_id', 0)
    model_id = item_data.get('model_id', 0)

    # 1. Khớp SKU chính xác
    if sku:
        line = so.order_line.filtered(lambda l: l.product_id.default_code == sku)
        if line:
            return line

    # 2. Khớp SKU sau khi normalize (bỏ space, uppercase)
    if sku:
        sku_norm = sku.replace(' ', '').upper()
        line = so.order_line.filtered(
            lambda l: (l.product_id.default_code or '').replace(' ', '').upper() == sku_norm
        )
        if line:
            _logger.info(
                "Shopee Escrow: Khớp SKU normalized '%s' → '%s'",
                sku, line[0].product_id.default_code,
            )
            return line

    # 3. Khớp qua bảng shopee.item (item_id + model_id)
    if item_id:
        domain = [('shopee_item_identifier', '=', str(item_id))]
        if model_id:
            domain.append(('shopee_model_identifier', '=', str(model_id)))
        shopee_item = so.env['shopee.item'].sudo().search(domain, limit=1)
        if shopee_item and shopee_item.product_id:
            product = shopee_item.product_id
            line = so.order_line.filtered(lambda l: l.product_id.id == product.id)
            if line:
                _logger.info(
                    "Shopee Escrow: Khớp qua shopee.item (item_id=%s, model_id=%s) → product=%s",
                    item_id, model_id, product.name,
                )
                return line

    return so.order_line.browse()  # empty recordset


def update_order_lines_from_escrow(so, escrow_data):
    """
    Cập nhật price_unit và discount cho các sale.order.line
    dựa trên danh sách items trong order_income của dữ liệu Escrow.

    Khớp sản phẩm theo thứ tự: SKU chính xác → SKU normalized → shopee.item mapping.

    :param so: sale.order record
    :param escrow_data: dict — giá trị của key 'response' từ Shopee escrow API
    """
    order_income = escrow_data.get('order_income', {})
    item_list = order_income.get('items', [])

    for item_data in item_list:
        sku = item_data.get('model_sku', '') or item_data.get('item_sku', '')

        line = _find_order_line_for_escrow_item(so, item_data)
        if not line:
            _logger.warning(
                "Shopee Escrow: Không tìm thấy dòng SP nào cho SKU='%s' item_id=%s trong đơn %s",
                sku, item_data.get('item_id', '?'), so.name,
            )
            continue

        qty = item_data.get('quantity_purchased', 1) or 1
        original_price = item_data.get('original_price', 0) / qty
        discounted_price = item_data.get('discounted_price', 0) / qty

        discount = 0.0
        if original_price > 0 and discounted_price is not None:
            discount = (original_price - discounted_price) / original_price * 100.0

        line_vals = {
            'price_unit': original_price,
            'discount': discount,
            'x_studio_thanh_tien_shopee': item_data.get('discounted_price', 0),
        }

        # Truy xuất Thuế include chính xác theo từng sản phẩm
        # Lấy sản phẩm của dòng đầu tiên (trong trường hợp 1 sku bị chia 2 line)
        tax_included = get_tax_included(so.env, so.company_id, line[0].product_id)
        if tax_included:
            line_vals['tax_id'] = [(6, 0, tax_included.ids)]

        line.sudo().write(line_vals)
        _logger.info(
            "Shopee Escrow: Đã update giá dòng SKU=%s: price=%s, discount=%.4f%%",
            sku, original_price, discount,
        )


def apply_escrow_voucher(so, escrow_data):
    """
    Phân bổ voucher shop (voucher_from_seller) vào discount % của các dòng SP.
    Dòng cuối nhận phần dư để tổng khớp chính xác (tránh lỗi làm tròn).

    :param so: sale.order record
    :param escrow_data: dict — giá trị của key 'response' từ Shopee escrow API
    """
    order_income = escrow_data.get('order_income', {})
    seller_voucher = order_income.get('voucher_from_seller', 0)

    if not seller_voucher:
        buyer_payment = escrow_data.get('buyer_payment_info', {})
        seller_voucher = abs(buyer_payment.get('seller_voucher', 0))

    total_voucher = abs(seller_voucher)
    if total_voucher <= 0:
        return

    lines = so.order_line.filtered(lambda l: not l.display_type and l.price_unit > 0)
    if not lines:
        return

    total_before_voucher = sum(
        l.price_unit * l.product_uom_qty * (1 - l.discount / 100.0)
        for l in lines
    )
    if total_before_voucher <= 0:
        return

    voucher_distributed = 0.0
    lines_list = list(lines)

    for i, line in enumerate(lines_list):
        line_total = line.price_unit * line.product_uom_qty
        if line_total <= 0:
            continue

        line_subtotal_before = line_total * (1 - line.discount / 100.0)

        if i < len(lines_list) - 1:
            line_voucher_share = (line_subtotal_before / total_before_voucher) * total_voucher
        else:
            # Dòng cuối nhận phần dư để tổng chính xác
            line_voucher_share = total_voucher - voucher_distributed

        voucher_distributed += line_voucher_share

        new_subtotal = line_subtotal_before - line_voucher_share
        if new_subtotal < 0:
            new_subtotal = 0.0

        new_discount = (1 - new_subtotal / line_total) * 100.0
        line.sudo().write({'discount': new_discount})

    _logger.info(
        "Shopee Escrow: Đã áp dụng voucher -%s vào discount các dòng đơn %s",
        total_voucher, so.name,
    )

def build_escrow_html_common(escrow_data, is_wizard=False):
    """
    Xây dựng chuỗi HTML hiển thị chi tiết Escrow (dùng chung cho Sale Order và Wizard).
    """
    if not escrow_data:
        if is_wizard:
             return "<p>Lỗi không tìm thấy dữ liệu Escrow trên đơn hàng. Vui lòng bấm 'Cập nhật giá Shopee' để lấy dữ liệu về.</p>"
        return ""

    def f_vnd(val):
        if isinstance(val, (int, float)):
            # Định dạng tiền VND: phân cách hàng nghìn bằng dấu chấm
            if abs(val) >= 100 or val == 0:
                return "{:,.0f}".format(val).replace(',', '.') + ' đ'
            return str(val)
        return str(val) if val is not None else ''

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
        'buyer_paid_shipping_fee': 'Phí vận chuyển khách trả (Income)',
        'buyer_service_fee': 'Phí dịch vụ khách trả',
        'buyer_tax_amount': 'Thuế khách trả',
        'buyer_transaction_fee': 'Phí giao dịch khách trả (Income)',
        'campaign_fee': 'Phí tham gia chương trình (Campaign Fee)',
        'coins': 'Shopee Xu',
        'commission_fee': 'Phí hoa hồng sàn (Commission Fee)',
        'cost_of_goods_sold': 'Giá trị đơn hàng (COGS/Selling Price)',
        'credit_card_promotion': 'Khuyến mãi thẻ tín dụng',
        'credit_card_transaction_fee': 'Phí giao dịch thẻ tín dụng',
        'cross_border_tax': 'Thuế xuyên biên giới',
        'delivery_seller_protection_fee_premium_amount': 'Phí bảo vệ người bán khi giao hàng',
        'discount_pix': 'Giảm giá Pix',
        'drc_adjustable_refund': 'Hoàn tiền điều chỉnh DRC',
        'escrow_amount': 'THỰC NHẬN (Escrow Amount)',
        'escrow_amount_after_adjustment': 'Thực nhận sau điều chỉnh',
        'escrow_import_tax': 'Thuế nhập khẩu Escrow',
        'escrow_tax': 'Thuế Escrow',
        'estimated_shipping_fee': 'Phí vận chuyển dự tính',
        'fbs_fee': 'Phí FBS',
        'final_escrow_product_gst': 'Thuế GST sản phẩm cuối cùng',
        'final_escrow_shipping_gst': 'Thuế GST vận chuyển cuối cùng',
        'final_product_protection': 'Bảo vệ sản phẩm cuối cùng',
        'final_product_vat_tax': 'Thuế GTGT sản phẩm cuối cùng',
        'final_return_to_seller_shipping_fee': 'Phí vận chuyển trả hàng cuối cùng',
        'final_shipping_fee': 'Phí vận chuyển cuối cùng',
        'final_shipping_vat_tax': 'Thuế GTGT vận chuyển cuối cùng',
        'footwear_tax': 'Thuế giày dép',
        'fsf_seller_protection_fee_claim_amount': 'Bồi thường bảo vệ người bán FSF',
        'icms_tax_amount': 'Thuế ICMS',
        'import_duty_and_excise_tax': 'Thuế nhập khẩu và tiêu thụ đặc biệt',
        'import_processing_charge': 'Phí xử lý nhập khẩu',
        'import_tax_amount': 'Thuế nhập khẩu',
        'initial_buyer_txn_fee': 'Phí giao dịch ban đầu của khách',
        'installation_fee_paid_by_buyer': 'Phí lắp đặt người mua trả',
        'instalment_plan': 'Kế hoạch trả góp',
        'insurance_premium': 'Phí bảo hiểm',
        'iof_tax_amount': 'Thuế IOF',
        'is_paid_by_credit_card': 'Thanh toán bằng thẻ tín dụng',
        'lvg_sales_tax_adjustment': 'Điều chỉnh thuế bán hàng LVG',
        'merchant_subtotal': 'Tổng tiền hàng (Subtotal)',
        'order_ams_commission_fee': 'Phí hoa hồng AMS',
        'order_chargeable_weight': 'Trọng lượng tính phí',
        'order_discounted_price': 'Giá sau giảm',
        'order_original_price': 'Giá gốc đơn hàng',
        'order_seller_discount': 'Tổng giảm giá từ người bán',
        'order_selling_price': 'Giá bán đơn hàng',
        'original_cost_of_goods_sold': 'Giá vốn hàng bán gốc',
        'original_price': 'Giá gốc',
        'original_shopee_discount': 'Giảm giá Shopee gốc',
        'overseas_return_service_fee': 'Phí dịch vụ trả hàng nước ngoài',
        'payment_promotion': 'Khuyến mãi thanh toán',
        'pix_discount': 'Giảm giá Pix (Seller)',
        'prorated_coins_value_offset_return_items': 'Xu phân bổ cho hàng trả',
        'prorated_payment_channel_promo_bank_offset_return_items': 'KM ngân hàng cho hàng trả',
        'prorated_payment_channel_promo_shopee_offset_return_items': 'KM Shopee cho hàng trả',
        'prorated_pix_discount_offset_return_items': 'Giảm giá Pix cho hàng trả',
        'prorated_seller_voucher_offset_return_items': 'Voucher Shop cho hàng trả',
        'prorated_shopee_voucher_offset_return_items': 'Voucher Shopee cho hàng trả',
        'return_to_seller_shipping_fee_sst': 'Thuế SST phí chuyển trả hàng',
        'reverse_shipping_fee': 'Phí vận chuyển ngược',
        'reverse_shipping_fee_sst': 'Thuế SST phí vận chuyển ngược',
        'rsf_seller_protection_fee_claim_amount': 'Bồi thường bảo vệ người bán RSF',
        'sales_tax_on_lvg': 'Thuế bán hàng trên LVG',
        'seller_coin_cash_back': 'Hoàn xu từ người bán',
        'seller_discount': 'Giảm giá từ Shop (Seller Discount)',
        'seller_lost_compensation': 'Bồi thường hàng thất lạc',
        'seller_order_processing_fee': 'Phí xử lý đơn hàng của shop',
        'seller_return_refund': 'Hoàn tiền trả hàng',
        'seller_shipping_discount': 'Hỗ trợ phí VC từ shop',
        'seller_transaction_fee': 'Phí giao dịch (Transaction Fee)',
        'seller_voucher': 'Voucher Shop (Buyer)',
        'seller_voucher_code': 'Mã Voucher Shop dùng',
        'service_fee': 'Phí dịch vụ (Service Fee)',
        'shipping_fee': 'Phí vận chuyển khách trả',
        'shipping_fee_discount_from_3pl': 'Giảm phí VC từ ĐVVC',
        'shipping_fee_sst': 'Thuế SST phí vận chuyển (Income)',
        'shipping_fee_sst_amount': 'Thuế SST phí vận chuyển',
        'shipping_seller_protection_fee_amount': 'Phí bảo vệ người bán (Vận chuyển)',
        'shopee_coins_redeemed': 'Shopee xu đã dùng',
        'shopee_discount': 'Hỗ trợ từ sàn (Shopee Discount)',
        'shopee_shipping_rebate': 'Shopee hỗ trợ phí VC',
        'shopee_voucher': 'Voucher Shopee (Buyer)',
        'tax_registration_code': 'Mã số thuế',
        'th_import_duty': 'Thuế nhập khẩu TH',
        'total_adjustment_amount': 'Tổng tiền điều chỉnh',
        'total_tax_and_fees_amount': 'Tổng thuế và phí',
        'trade_in_bonus': 'Thưởng thu cũ đổi mới',
        'trade_in_bonus_by_seller': 'Thưởng thu cũ đổi mới từ shop',
        'trade_in_discount': 'Giảm giá thu cũ đổi mới',
        'vat': 'Thuế GTGT (VAT)',
        'vat_on_imported_goods': 'Thuế GTGT hàng nhập khẩu',
        'voucher_from_seller': 'Voucher từ Shop (Seller Voucher)',
        'voucher_from_shopee': 'Voucher từ Shopee (Seller)',
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

    html_start = ""
    html_end = ""
    if is_wizard:
        html_start = '<table class="table table-bordered table-sm" style="width: 100%; margin-bottom: 0;">'
        html_end = '</table>'
    else:
        html_start = f"""
        <details style="border: 1px solid #ddd; border-radius: 4px; padding: 10px; margin-top: 10px; background: #fafafa; width: 100%;">
            <summary style="cursor: pointer; color: #017e84; font-weight: bold; list-style: none; outline: none; margin-bottom: 0;">
                <i class="fa fa-caret-down pe-2"></i> Chi tiết phí &amp; chiết khấu Shopee (Escrow)
            </summary>
            <div style="margin-top: 15px;">
                <table class="table table-bordered table-sm" style="width: 100%; margin-bottom: 0; background: #fff;">
        """
        html_end = "</table></div></details>"

    def render_dict_to_rows(data_dict, title):
        if not data_dict:
            return ""

        filtered_data = {
            k: v for k, v in data_dict.items() 
            if k not in ignore_keys 
            and not isinstance(v, (dict, list))
            and v != 0 and v != 0.0 and v != ""
        }
        
        if not filtered_data:
            return ""

        res = f'''<thead class="bg-light">
            <tr><th colspan="2" style="font-size: 1.05em; color: #333; padding-top: 10px; border-top: 2px solid #dee2e6;">{title}</th></tr>
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

    html = html_start
    
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

    html += html_end
    return html