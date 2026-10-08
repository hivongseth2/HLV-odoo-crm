# -*- coding: utf-8 -*-
"""Trao đổi sale/thu mua ↔ NCC trên một báo giá (hlv.vendor.quote) hoặc đơn mua.

Tin nhắn là mail.message thường (hiện cả trong chatter backend), đánh dấu bằng subtype
riêng mt_vendor_chat; có thể kèm ảnh / tệp. Đọc / ghi đều bằng sudo: NCC là khách công khai,
sale không có quyền trên đơn mua — controller phải kiểm phạm vi (link NCC / mã sale) TRƯỚC
khi gọi vào đây, kể cả khi tải tệp (chat_attachment chỉ trả về record để controller kiểm).
"""

from odoo.exceptions import UserError
from odoo.tools import html2plaintext, plaintext2html

from ..models.vendor_quote_utils import (
    DATETIME_FMT, IMAGE_EXTENSIONS, attachment_error, file_extension, local_date_text,
)
from .chat_bus import notify_chat
from .notify import internal_followers

CHAT_SUBTYPE = "hlv_vendor_quotation.mt_vendor_chat"
CHAT_MODELS = ("hlv.vendor.quote", "purchase.order")
MESSAGE_MAX = 2000
FILE_MAX_BYTES = 10 * 1024 * 1024
FILES_PER_MESSAGE = 5


def _is_internal(partner):
    return bool(partner.user_ids.filtered(lambda user: not user.share))


def author_label(record, author):
    """Tên người nhắn để hiện trên trang NCC / trang sale: tên CÔNG TY, không phải tên tài
    khoản — một tài khoản Odoo nhiều người dùng chung, hiện tên user (VD "Administrator") vừa
    vô nghĩa vừa lộ tài khoản. Bên mình → tên công ty của chứng từ; NCC → tên công ty NCC."""
    if _is_internal(author):
        return (record.sudo().company_id or record.env.company).name or ""
    return author.commercial_partner_id.name or ""


def display_time(value):
    """Datetime UTC (naive, như Odoo lưu) → "HH:MM dd/mm/YYYY" giờ Việt Nam; rỗng → ""."""
    return local_date_text(value, DATETIME_FMT)


def chat_messages(record, file_url=None):
    """Tin trao đổi của record, cũ trước mới sau. Bỏ mọi tin hệ thống / ghi chú nội bộ.

    file_url: hàm attachment_id → link tải (mỗi trang một route có kiểm quyền riêng); không
    truyền thì không trả danh sách tệp.
    """
    subtype = record.env.ref(CHAT_SUBTYPE)
    messages = record.sudo().message_ids.filtered(
        lambda m: m.subtype_id == subtype and m.message_type == "comment"
    ).sorted("id")
    return [
        {
            "id": message.id,
            "author": author_label(record, message.author_id),
            # Mã sale đang chọn trên /hoi-gia-ncc khi gửi (rỗng: gửi ở chế độ "tất cả" / backend).
            "sale_code": message.hlv_sale_code or "",
            "from_vendor": not _is_internal(message.author_id),
            "at": message.date,
            "date": display_time(message.date),
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


def post_chat(record, text, author, from_vendor, notify_partners=None, files=None, sale_code=""):
    """Đăng một tin trao đổi, có thể kèm tệp. text: chữ thường NCC / sale gõ (được escape).

    files: list (tên tệp, nội dung bytes). Tệp sai loại / quá lớn → UserError, không đăng gì.
    sale_code: mã sale đang chọn trên trang sale — ghi vào tin để biết sale nào nhắn.
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
    # Tệp đưa qua `attachments` để message_post tự tạo và gắn vào tin. KHÔNG tạo ir.attachment
    # trước rồi truyền attachment_ids: với người gửi không phải user nội bộ (NCC trên trang công
    # khai — sudo không đổi env.user), Odoo bỏ mọi attachment_ids không tạo từ hộp soạn thư, nên
    # tin của NCC mất hết ảnh / tệp.
    message = record.message_post(
        body=plaintext2html(text[:MESSAGE_MAX]) if text else "",
        author_id=author.id,
        message_type="comment",
        subtype_xmlid=CHAT_SUBTYPE,
        attachments=files,
        partner_ids=(internal_followers(record) | (notify_partners or record.env["res.partner"])).ids
        if from_vendor else [],
    )
    if sale_code:
        message.hlv_sale_code = sale_code
    notify_chat(record, author_label(record, author), from_vendor)


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
