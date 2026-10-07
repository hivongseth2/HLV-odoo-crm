# -*- coding: utf-8 -*-
"""Thông báo trên trang NCC: yêu cầu báo giá mới, đơn mua mới, tin nhắn của bên mua — mỗi
mục kèm đã xem / chưa xem (mốc ở services/chat_read.py).

- Báo giá: chưa xem khi NCC chưa mở lần nào VÀ chưa gửi giá (đã gửi giá thì hẳn đã xem —
  tránh báo cả loạt báo giá cũ có từ trước khi có thông báo).
- Đơn mua: chưa xem khi NCC chưa mở lần nào.
- Tin nhắn: tin bên mua sau mốc đã xem của NCC trên báo giá / đơn mua đó.
"""

from ..models.vendor_quote import VENDOR_VISIBLE_STATES
from .chat_read import is_seen, seen_markers, unread_messages
from .vendor_chat import chat_messages, display_time

FEED_LIMIT = 20
EXCERPT_MAX = 120


def _excerpt(message):
    body = message["body"]
    if body:
        return body if len(body) <= EXCERPT_MAX else body[:EXCERPT_MAX].rstrip() + "…"
    return "Đã gửi tệp đính kèm"


def _record_items(record, path, markers, access):
    """Các mục thông báo của một báo giá / đơn mua: chính chứng từ + tin của bên mua."""
    is_quote = record._name == "hlv.vendor.quote"
    items = [{
        "title": "Yêu cầu báo giá mới" if is_quote else "Đơn mua mới",
        "name": record.name,
        "text": "",
        "at": record.create_date if is_quote else (record.date_approve or record.date_order),
        "unread": _is_new(record, markers),
        "url": path,
    }]
    messages = chat_messages(record)
    unread_ids = {m["id"] for m in unread_messages(record, access, markers, messages)}
    items += [
        {
            "title": f"{message['author']} nhắn",
            "name": record.name,
            "text": _excerpt(message),
            "at": message["at"],
            "unread": message["id"] in unread_ids,
            "url": f"{path}#trao-doi",
        }
        for message in messages if not message["from_vendor"]
    ]
    return items


def vendor_feed(access, portal_base, limit=FEED_LIMIT):
    """{"items": [mục mới nhất trước, tối đa limit], "unread": tổng số mục chưa xem}.

    Mỗi mục: title, name (số chứng từ), text (trích tin), date (chuỗi giờ VN), unread, url.
    """
    quotes = access.sudo().quote_ids.filtered(lambda q: q.state in VENDOR_VISIBLE_STATES)
    orders = access._vendor_purchase_orders()
    markers = seen_markers(list(quotes) + list(orders), access)
    items = []
    for quote in quotes:
        items += _record_items(quote, f"{portal_base}/{quote.id}", markers, access)
    for order in orders:
        items += _record_items(order, f"{portal_base}/don-mua/{order.id}", markers, access)
    items.sort(key=lambda item: item["at"], reverse=True)
    for item in items:
        item["date"] = display_time(item.pop("at"))
    return {"items": items[:limit], "unread": sum(1 for item in items if item["unread"])}


def _is_new(record, markers):
    """Chứng từ NCC chưa mở lần nào (báo giá đã gửi giá thì coi như đã xem — xem đầu file)."""
    if record._name == "hlv.vendor.quote" and record.submit_date:
        return False
    return not is_seen(record, markers)


def row_marks(records, access):
    """{id: {"unread": số tin bên mua chưa xem, "new": chưa mở lần nào}} cho các record cùng
    model — đánh dấu dòng trong bảng của NCC."""
    markers = seen_markers(list(records), access)
    return {
        record.id: {"unread": len(unread_messages(record, access, markers)), "new": _is_new(record, markers)}
        for record in records
    }
