# -*- coding: utf-8 -*-
"""Trao đổi sale/thu mua ↔ NCC trên một báo giá (hlv.vendor.quote) hoặc đơn mua.

Tin nhắn là mail.message thường (hiện cả trong chatter backend), đánh dấu bằng subtype
riêng mt_vendor_chat. Đọc / ghi đều bằng sudo: NCC là khách công khai, sale không có quyền
trên đơn mua — controller phải kiểm phạm vi (link NCC / mã sale) TRƯỚC khi gọi vào đây.
"""

import pytz

from odoo.exceptions import UserError
from odoo.tools import html2plaintext, plaintext2html

from .notify import internal_followers

CHAT_SUBTYPE = "hlv_vendor_quotation.mt_vendor_chat"
MESSAGE_MAX = 2000
DISPLAY_TZ = "Asia/Ho_Chi_Minh"


def _is_internal(partner):
    return bool(partner.user_ids.filtered(lambda user: not user.share))


def chat_messages(record):
    """Tin trao đổi của record, cũ trước mới sau. Bỏ mọi tin hệ thống / ghi chú nội bộ."""
    subtype = record.env.ref(CHAT_SUBTYPE)
    messages = record.sudo().message_ids.filtered(
        lambda m: m.subtype_id == subtype and m.message_type == "comment"
    ).sorted("id")
    tz = pytz.timezone(DISPLAY_TZ)
    return [
        {
            "id": message.id,
            "author": message.author_id.name or "",
            "from_vendor": not _is_internal(message.author_id),
            "date": pytz.utc.localize(message.date).astimezone(tz).strftime("%H:%M %d/%m/%Y"),
            "body": html2plaintext(message.body or "").strip(),
        }
        for message in messages
    ]


def chat_stats(record):
    """(số tin, tin cuối có phải của NCC không) — để báo "NCC vừa nhắn" trên trang sale."""
    messages = chat_messages(record)
    return len(messages), bool(messages and messages[-1]["from_vendor"])


def post_chat(record, text, author, from_vendor, notify_partners=None):
    """Đăng một tin trao đổi. text: chữ thường NCC / sale gõ (được escape khi chuyển HTML).

    Tin của NCC gọi tên follower nội bộ + notify_partners (sale tạo phiếu, người phụ trách
    đơn mua) để họ nhận thông báo trong Odoo; tin của sale không gửi đi đâu — NCC đọc trên
    trang báo giá của họ.
    """
    text = (text or "").strip()
    if not text:
        raise UserError("Chưa nhập nội dung tin nhắn.")
    # mail_create_nosubscribe: không để tác giả (nhất là NCC) tự thành follower — xem notify.py.
    record = record.sudo().with_context(mail_create_nosubscribe=True)
    record.message_post(
        body=plaintext2html(text[:MESSAGE_MAX]),
        author_id=author.id,
        message_type="comment",
        subtype_xmlid=CHAT_SUBTYPE,
        partner_ids=(internal_followers(record) | (notify_partners or record.env["res.partner"])).ids
        if from_vendor else [],
    )
