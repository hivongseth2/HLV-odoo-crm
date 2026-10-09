# -*- coding: utf-8 -*-
"""Chuông thông báo trên trang /hoi-gia-ncc: báo giá NCC vừa gửi / cập nhật, tiến độ đơn mua đổi.

"Mới" = gửi sau lần cuối người dùng mở chuông (res.users.hlv_vq_bell_seen_at). Đọc theo quyền
người dùng (không sudo), lọc theo mã sale đã kiểm — như danh sách phiếu.
"""

from datetime import timedelta

from odoo import fields

from ..models.vendor_quote_utils import DATETIME_FMT, local_date_text
from . import sale_scope

FEED_DAYS = 14
FEED_LIMIT = 20
# Chưa mở chuông lần nào (vừa có tính năng): chỉ coi báo giá trong 1 ngày qua là mới — không thì
# lần đầu chuông báo cả loạt báo giá cũ.
FIRST_SEEN_DAYS = 1


def _domain(scope, since):
    return sale_scope.scope_domain(scope, "inquiry_id.sale_code") + [
        ("inquiry_id", "!=", False),
        ("state", "in", ("quoted", "done")),
        ("submit_date", ">=", since),
    ]


def quote_feed(env, scope):
    """Chuông trang sale: {"items": [mới nhất trước, tối đa FEED_LIMIT, trong FEED_DAYS ngày], "unread": số
    mục sau mốc đã xem}. Hai loại mục (khoá "kind"): "quote" — NCC gửi / cập nhật báo giá; "order" — tiến
    độ đơn mua đổi (NCC đóng gói / gửi hàng, kho nhận hàng). scope: mã sale đã kiểm (False = mọi mã)."""
    now = fields.Datetime.now()
    since = now - timedelta(days=FEED_DAYS)
    Quote = env["hlv.vendor.quote"]
    domain = _domain(scope, since)
    seen_at = env.user.hlv_vq_bell_seen_at or now - timedelta(days=FIRST_SEEN_DAYS)
    quotes = Quote.search(domain, order="submit_date desc, id desc", limit=FEED_LIMIT)
    entries = [(quote.submit_date, _quote_item(quote, seen_at)) for quote in quotes]
    orders = _order_events(env, scope, since)
    entries += [(order.hlv_vendor_status_date, _order_item(order, scope, seen_at)) for order in orders]
    entries.sort(key=lambda entry: entry[0], reverse=True)
    return {
        "unread": Quote.search_count(domain + [("submit_date", ">", seen_at)])
        + sum(1 for order in orders if order.hlv_vendor_status_date > seen_at),
        "items": [item for _at, item in entries[:FEED_LIMIT]],
    }


def _quote_item(quote, seen_at):
    return {
        "kind": "quote",
        "quote_id": quote.id,
        "quote_name": quote.name,
        "inquiry_id": quote.inquiry_id.id,
        "inquiry_name": quote.inquiry_id.name,
        "vendor": quote.partner_id.commercial_partner_id.display_name,
        "offered": len(quote.line_ids.filtered(lambda l: not l.unavailable)),
        "total": len(quote.line_ids),
        "amount_total": quote.amount_total,
        "date": local_date_text(quote.submit_date, DATETIME_FMT),
        "unread": quote.submit_date > seen_at,
    }


def _order_events(env, scope, since):
    """Đơn mua đổi tiến độ trong FEED_DAYS ngày, lên từ phiếu hỏi giá thuộc mã sale đang xem. Đọc bằng
    sudo (sale không có quyền đơn mua) — chỉ đưa số đơn / NCC / tiến độ, mở phiếu vẫn qua API đã kiểm."""
    orders = env["purchase.order"].sudo().search(
        [("hlv_vendor_status_date", ">=", since)], order="hlv_vendor_status_date desc", limit=FEED_LIMIT * 3,
    )
    return orders.filtered(lambda order: _scoped_inquiries(order, scope))[:FEED_LIMIT]


def _scoped_inquiries(order, scope):
    inquiries = order.hlv_inquiry_ids
    return inquiries if not scope else inquiries.filtered(lambda i: (i.sale_code or "").upper() == scope.upper())


def _order_item(order, scope, seen_at):
    from ..models.purchase_order import PROGRESS_LABELS  # tránh vòng import với models
    inquiry = _scoped_inquiries(order, scope)[:1]
    return {
        "kind": "order",
        "order_id": order.id,
        "order_name": order.name,
        "inquiry_id": inquiry.id,
        "inquiry_name": inquiry.name,
        "vendor": order.partner_id.commercial_partner_id.display_name,
        "status": PROGRESS_LABELS.get(order._hlv_vendor_progress(), ""),
        "ship": order._hlv_ship_text(),
        "date": local_date_text(order.hlv_vendor_status_date, DATETIME_FMT),
        "unread": order.hlv_vendor_status_date > seen_at,
    }


def mark_feed_seen(env):
    """Người dùng vừa mở chuông: mọi báo giá gửi tới giờ coi như đã xem."""
    env.user.sudo().hlv_vq_bell_seen_at = fields.Datetime.now()
