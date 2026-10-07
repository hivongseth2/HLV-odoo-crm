# -*- coding: utf-8 -*-
"""Trao đổi sale/thu mua ↔ NCC trên một báo giá (hlv.vendor.quote) hoặc đơn mua.

Tin nhắn là mail.message thường (hiện cả trong chatter backend), đánh dấu bằng subtype
riêng mt_vendor_chat; có thể kèm ảnh / tệp. Đọc / ghi đều bằng sudo: NCC là khách công khai,
sale không có quyền trên đơn mua — controller phải kiểm phạm vi (link NCC / mã sale) TRƯỚC
khi gọi vào đây, kể cả khi tải tệp (chat_attachment chỉ trả về record để controller kiểm).
"""

import pytz

from odoo.exceptions import UserError
from odoo.tools import html2plaintext, plaintext2html

from ..models.vendor_quote_utils import IMAGE_EXTENSIONS, attachment_error, file_extension
from .notify import internal_followers

CHAT_SUBTYPE = "hlv_vendor_quotation.mt_vendor_chat"
CHAT_MODELS = ("hlv.vendor.quote", "purchase.order")
MESSAGE_MAX = 2000
FILE_MAX_BYTES = 10 * 1024 * 1024
FILES_PER_MESSAGE = 5
DISPLAY_TZ = "Asia/Ho_Chi_Minh"


def _is_internal(partner):
    return bool(partner.user_ids.filtered(lambda user: not user.share))


def chat_messages(record, file_url=None):
    """Tin trao đổi của record, cũ trước mới sau. Bỏ mọi tin hệ thống / ghi chú nội bộ.

    file_url: hàm attachment_id → link tải (mỗi trang một route có kiểm quyền riêng); không
    truyền thì không trả danh sách tệp.
    """
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
            "attachments": [
                {
                    "id": attachment.id,
                    "name": attachment.name,
                    "is_image": file_extension(attachment.name) in IMAGE_EXTENSIONS,
                    "url": file_url(attachment.id),
                }
                for attachment in message.attachment_ids
            ] if file_url else [],
        }
        for message in messages
    ]


def chat_stats(record):
    """(số tin, tin cuối có phải của NCC không) — để báo "NCC vừa nhắn" trên trang sale."""
    messages = chat_messages(record)
    return len(messages), bool(messages and messages[-1]["from_vendor"])


def post_chat(record, text, author, from_vendor, notify_partners=None, files=None):
    """Đăng một tin trao đổi, có thể kèm tệp. text: chữ thường NCC / sale gõ (được escape).

    files: list (tên tệp, nội dung bytes). Tệp sai loại / quá lớn → UserError, không đăng gì.
    Tin của NCC gọi tên follower nội bộ + notify_partners (sale tạo phiếu, người phụ trách
    đơn mua) để họ nhận thông báo trong Odoo; tin của sale không gửi đi đâu — NCC đọc trên
    trang báo giá của họ.
    """
    text = (text or "").strip()
    files = [(name, data) for name, data in (files or []) if name or data]
    if not text and not files:
        raise UserError("Chưa nhập nội dung tin nhắn hoặc chọn tệp.")
    if len(files) > FILES_PER_MESSAGE:
        raise UserError(f"Mỗi tin gửi tối đa {FILES_PER_MESSAGE} tệp.")
    errors = [attachment_error(name, len(data), FILE_MAX_BYTES) for name, data in files]
    errors = [error for error in errors if error]
    if errors:
        raise UserError("\n".join(errors))

    # mail_create_nosubscribe: không để tác giả (nhất là NCC) tự thành follower — xem notify.py.
    record = record.sudo().with_context(mail_create_nosubscribe=True)
    attachments = record.env["ir.attachment"].create([
        {"name": name, "raw": data, "res_model": record._name, "res_id": record.id}
        for name, data in files
    ])
    record.message_post(
        body=plaintext2html(text[:MESSAGE_MAX]) if text else "",
        author_id=author.id,
        message_type="comment",
        subtype_xmlid=CHAT_SUBTYPE,
        attachment_ids=attachments.ids,
        partner_ids=(internal_followers(record) | (notify_partners or record.env["res.partner"])).ids
        if from_vendor else [],
    )


def chat_attachment(env, attachment_id):
    """Tệp thuộc một tin trao đổi → (tệp, record của cuộc trao đổi), đều sudo.

    Không phải tệp của tin trao đổi → (None, None). Controller vẫn phải kiểm record có thuộc
    người đang xem không.
    """
    attachment = env["ir.attachment"].sudo().browse(attachment_id).exists()
    if not attachment or attachment.res_model not in CHAT_MODELS:
        return None, None
    message = env["mail.message"].sudo().search([
        ("attachment_ids", "in", attachment.ids),
        ("subtype_id", "=", env.ref(CHAT_SUBTYPE).id),
    ], limit=1)
    if not message:
        return None, None
    return attachment, env[message.model].sudo().browse(message.res_id).exists()
