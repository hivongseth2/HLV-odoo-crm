# -*- coding: utf-8 -*-
"""Hàm thuần dùng chung cho API Zalo Mini App."""


def effective_zalo_price(zalo_price, pricelist_price, list_price):
    """Đơn giá khách phải trả cho một sản phẩm trên Mini App.

    Khớp với `getProductPriceInfo` phía app (giá đang hiển thị cho khách):
    ưu tiên giá Zalo, rồi giá theo bảng giá, cuối cùng là giá niêm yết.

    Nhận ba số (None hoặc <= 0 coi như không có), trả số > 0 đầu tiên theo thứ
    tự trên; cả ba đều không có thì trả 0.0 — nơi gọi phải coi là "chưa có giá,
    không bán" chứ không tạo dòng 0 đ.
    """
    for price in (zalo_price, pricelist_price, list_price):
        if price and price > 0:
            return float(price)
    return 0.0
