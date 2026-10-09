# -*- coding: utf-8 -*-
"""Chuông thông báo trên trang /hoi-gia-ncc: báo giá NCC vừa gửi / cập nhật.

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
    """{"items": [báo giá gửi gần nhất trước, tối đa FEED_LIMIT, trong FEED_DAYS ngày], "unread": số
    báo giá gửi sau mốc đã xem}. scope: mã sale đã kiểm (False = mọi mã)."""
    now = fields.Datetime.now()
    Quote = env["hlv.vendor.quote"]
    domain = _domain(scope, now - timedelta(days=FEED_DAYS))
    seen_at = env.user.hlv_vq_bell_seen_at or now - timedelta(days=FIRST_SEEN_DAYS)
    quotes = Quote.search(domain, order="submit_date desc, id desc", limit=FEED_LIMIT)
    return {
        "unread": Quote.search_count(domain + [("submit_date", ">", seen_at)]),
        "items": [
            {
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
            for quote in quotes
        ],
    }


def mark_feed_seen(env):
    """Người dùng vừa mở chuông: mọi báo giá gửi tới giờ coi như đã xem."""
    env.user.sudo().hlv_vq_bell_seen_at = fields.Datetime.now()
