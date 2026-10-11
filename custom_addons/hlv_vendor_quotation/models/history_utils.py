# -*- coding: utf-8 -*-
"""Hàm thuần cho trang "Lịch sử báo giá" của NCC — không đụng env."""

from datetime import datetime, time, timedelta

import pytz

from .vendor_quote_utils import LOCAL_TZ

# Kết quả một dòng báo giá của NCC, theo thứ tự ưu tiên khi xét (line_outcome).
OUTCOMES = [
    ("ordered", "Lên đơn mua"),
    ("selected", "Được chọn"),
    ("lost", "Không được chọn"),
    ("pending", "Chờ bên mua chọn"),
    ("na", "Hết hàng"),
]
WON_OUTCOMES = ("ordered", "selected")


def day_range_utc(day_from, day_to, tz_name=LOCAL_TZ):
    """Khoảng ngày theo giờ địa phương → (từ, tới) datetime naive UTC để lọc Datetime của Odoo.

    day_from / day_to: date hoặc None. "tới" là đầu ngày SAU day_to (lọc dùng <), để trọn ngày cuối.
    Thiếu đầu nào thì đầu đó None (không giới hạn). day_from > day_to thì đổi chỗ.
    """
    if day_from and day_to and day_from > day_to:
        day_from, day_to = day_to, day_from
    tz = pytz.timezone(tz_name)

    def to_utc(day):
        return tz.localize(datetime.combine(day, time())).astimezone(pytz.utc).replace(tzinfo=None)

    return (to_utc(day_from) if day_from else None, to_utc(day_to + timedelta(days=1)) if day_to else None)


def line_outcome(unavailable, ordered, selected, decided):
    """Kết quả một dòng NCC đã báo: "na" (báo hết hàng), "ordered" (đã lên đơn mua của NCC), "selected"
    (bên mua chọn giá này, chưa lên đơn), "lost" (bên mua đã quyết — chọn NCC khác / đóng phiếu), hoặc
    "pending" (chưa quyết)."""
    if unavailable:
        return "na"
    if ordered:
        return "ordered"
    if selected:
        return "selected"
    return "lost" if decided else "pending"


def success_rate(won, lost):
    """Tỉ lệ báo giá thành công (%, số nguyên) = được chọn hoặc lên đơn / (đó + không được chọn).

    Dòng còn chờ bên mua chọn và dòng hết hàng không tính — chưa có kết quả / NCC không báo giá.
    Chưa dòng nào có kết quả → None.
    """
    total = won + lost
    return round(won * 100 / total) if total else None


def aggregate_products(rows):
    """Thống kê theo mặt hàng từ các dòng lịch sử.

    rows: [{product_id, product, outcome, order_ids (set id đơn mua), price_incl, at (datetime)}].
    Trả list dict {product_id, product, asked (lượt được hỏi), priced (lượt có giá), won, lost, rate,
    orders (số đơn mua khác nhau), last_price (giá sau VAT lần báo gần nhất có giá; 0 nếu chưa có giá)},
    sắp theo lượt hỏi giảm dần, cùng lượt thì mặt hàng báo gần đây hơn lên trước. rows rỗng → [].
    """
    stats = {}
    for row in rows:
        item = stats.setdefault(row["product_id"], {
            "product_id": row["product_id"], "product": row["product"], "asked": 0, "priced": 0, "won": 0, "lost": 0,
            "order_ids": set(), "last_price": 0.0, "last_at": None, "priced_at": None,
        })
        item["asked"] += 1
        item["order_ids"] |= row["order_ids"]
        item["won"] += row["outcome"] in WON_OUTCOMES
        item["lost"] += row["outcome"] == "lost"
        if item["last_at"] is None or row["at"] > item["last_at"]:
            item["last_at"] = row["at"]
        if row["outcome"] != "na":
            item["priced"] += 1
            if item["priced_at"] is None or row["at"] > item["priced_at"]:
                item["priced_at"], item["last_price"] = row["at"], row["price_incl"]
    result = []
    for item in stats.values():
        result.append({
            "product_id": item["product_id"], "product": item["product"], "asked": item["asked"],
            "priced": item["priced"], "won": item["won"], "lost": item["lost"],
            "rate": success_rate(item["won"], item["lost"]), "orders": len(item["order_ids"]),
            "last_price": item["last_price"], "last_at": item["last_at"],
        })
    result.sort(key=lambda r: (-r["asked"], -(r["last_at"].timestamp() if r["last_at"] else 0)))
    return result
