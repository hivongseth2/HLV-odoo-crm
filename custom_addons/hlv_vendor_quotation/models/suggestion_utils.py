# -*- coding: utf-8 -*-
"""Gợi ý NCC cho TỪNG mặt hàng theo 3 tiêu chí, từ dòng đơn mua đã xác nhận. Util thuần: vào list, ra dict.

- Giá rẻ nhất: giá mua LẦN GẦN NHẤT của mỗi NCC (giá cũ của một NCC không còn đúng), lấy NCC thấp nhất.
- Đã giao: NCC từng giao được hàng (kho nhận > 0) — nhiều lần nhận hơn lên trước.
- Mua gần nhất: NCC của đơn mua mặt hàng đó gần đây nhất ("NCC mới" theo cách thu mua gọi).
"""

PICK_CHEAPEST = "cheapest"
PICK_DELIVERED = "delivered"
PICK_RECENT = "recent"


def vendor_picks(rows):
    """Chọn NCC theo 3 tiêu chí cho từng sản phẩm.

    Nhận: iterable dict ``{"product_id", "partner_id", "price" (giá theo ĐVT sản phẩm, tiền công ty),
    "date" (ngày đặt — so sánh được, không None), "received" (SL kho đã nhận)}``.
    Trả: ``{product_id: {"cheapest": partner_id|None, "delivered": partner_id|None, "delivered_count": int,
    "recent": partner_id|None, "recent_date": date|None, "vendors": set(partner_id)}}``.
    Giá ≤ 0 (hàng tặng, chưa có giá) không dự "rẻ nhất"; hoà giá thì NCC mua gần hơn. Không dòng nào → {}.
    """
    by_product = {}
    for row in rows:
        by_product.setdefault(row["product_id"], []).append(row)
    result = {}
    for product_id, items in by_product.items():
        latest = {}
        receipts = {}
        for row in items:
            vendor = row["partner_id"]
            if vendor not in latest or row["date"] > latest[vendor]["date"]:
                latest[vendor] = row
            if (row["received"] or 0) > 0:
                count, last = receipts.get(vendor, (0, None))
                receipts[vendor] = (count + 1, row["date"] if last is None or row["date"] > last else last)
        priced = [row for row in latest.values() if (row["price"] or 0) > 0]
        cheapest = min(priced, key=lambda r: (r["price"], -r["date"].toordinal())) if priced else None
        delivered = max(receipts.items(), key=lambda item: (item[1][0], item[1][1])) if receipts else None
        recent = max(items, key=lambda r: r["date"])
        result[product_id] = {
            PICK_CHEAPEST: cheapest["partner_id"] if cheapest else None,
            PICK_DELIVERED: delivered[0] if delivered else None,
            "delivered_count": delivered[1][0] if delivered else 0,
            PICK_RECENT: recent["partner_id"],
            "recent_date": recent["date"],
            "vendors": set(latest),
        }
    return result
