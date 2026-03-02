# -*- coding: utf-8 -*-
"""
services/shopee_escrow.py

Xử lý dữ liệu Escrow từ Shopee: cập nhật giá theo items, áp dụng voucher.
Các hàm ở đây nhận `sale.order` record làm tham số và thực hiện write trực tiếp.
"""
import logging

_logger = logging.getLogger(__name__)


def get_tax_included(env, company):
    """
    Tìm thuế bán hàng có price_include=True trong công ty chỉ định.
    Trả về account.tax record hoặc False.
    """
    Tax = env['account.tax'].sudo()
    tax = Tax.search([
        ('type_tax_use', '=', 'sale'),
        ('price_include', '=', True),
        ('company_id', '=', company.id),
    ], limit=1)
    if tax:
        return tax

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


def update_order_lines_from_escrow(so, escrow_data):
    """
    Cập nhật price_unit và discount cho các sale.order.line
    dựa trên danh sách items trong order_income của dữ liệu Escrow.

    Khớp sản phẩm theo model_sku (hoặc item_sku nếu model_sku rỗng)
    với default_code của product.product trong Odoo.

    :param so: sale.order record
    :param escrow_data: dict — giá trị của key 'response' từ Shopee escrow API
    """
    order_income = escrow_data.get('order_income', {})
    item_list = order_income.get('items', [])

    tax_included = get_tax_included(so.env, so.company_id)

    for item_data in item_list:
        sku = item_data.get('model_sku', '') or item_data.get('item_sku', '')
        if not sku:
            continue

        line = so.order_line.filtered(lambda l: l.product_id.default_code == sku)
        if not line:
            _logger.debug("Shopee Escrow: Không tìm thấy dòng SP có SKU '%s' trong đơn %s", sku, so.name)
            continue

        original_price = item_data.get('original_price', 0)
        discounted_price = item_data.get('discounted_price', 0)

        discount = 0.0
        if original_price and discounted_price and original_price > 0:
            discount = (original_price - discounted_price) / original_price * 100.0

        line_vals = {
            'price_unit': original_price,
            'discount': discount,
        }
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
