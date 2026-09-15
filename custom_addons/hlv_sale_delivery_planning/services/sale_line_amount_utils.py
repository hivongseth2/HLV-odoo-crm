# -*- coding: utf-8 -*-
"""Tính tiền theo số lượng thực giao của một dòng đơn bán.

Tách riêng vì hai chỗ cần đúng một công thức: bảng sản phẩm trong drawer
/sale_plan (theo SL đã giao của cả đơn) và bảng dòng hàng của từng phiếu xuất
kho (theo SL giao của riêng phiếu đó). Hai nơi tính lệch nhau là ra hai con số
tiền khác nhau cho cùng một đơn.
"""


def compute_line_amounts(sale_line, quantity):
    """Tiền của `quantity` đơn vị trên một dòng đơn bán.

    :param sale_line: record sale.order.line (1 dòng) hoặc giá trị falsy.
    :param quantity: số lượng cần tính tiền (float).
    :return: dict gồm price_unit, discount, price_after_discount (đơn giá sau
             chiết khấu), subtotal (trước thuế), tax (tiền thuế), total (sau thuế).
             Không có dòng hoặc quantity <= 0 → mọi giá trị tiền bằng 0
             (price_unit/discount vẫn trả theo dòng nếu có, để còn hiển thị).
    """
    price_unit = sale_line.price_unit if sale_line else 0.0
    discount = sale_line.discount if sale_line else 0.0
    price_after_discount = price_unit * (1.0 - (discount or 0.0) / 100.0)

    empty = {
        'price_unit': price_unit,
        'discount': discount,
        'price_after_discount': price_after_discount,
        'subtotal': 0.0,
        'tax': 0.0,
        'total': 0.0,
    }
    if not sale_line or not quantity or quantity <= 0:
        return empty

    if not sale_line.tax_id:
        subtotal = price_after_discount * quantity
        return dict(empty, subtotal=subtotal, tax=0.0, total=subtotal)

    # round=False: để thuế cộng dồn nhiều dòng không bị lệch do làm tròn từng dòng.
    tax_res = sale_line.tax_id.with_context(round=False).compute_all(
        price_after_discount,
        currency=sale_line.order_id.currency_id,
        quantity=quantity,
        product=sale_line.product_id,
        partner=sale_line.order_id.partner_shipping_id,
    )
    return dict(
        empty,
        subtotal=tax_res['total_excluded'],
        tax=sum(t['amount'] for t in tax_res['taxes']),
        total=tax_res['total_included'],
    )
