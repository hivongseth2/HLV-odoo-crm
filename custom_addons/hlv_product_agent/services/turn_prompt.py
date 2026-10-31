# -*- coding: utf-8 -*-
"""Dựng nội dung một lượt gửi cho Claude từ các tin nhắn của sale.

Util thuần: vào dữ liệu thường (dict/list), ra chuỗi. Không đụng ``self.env``.
"""
import os

from .permission_marker import apply_permission_marker, strip_permission_markers

# Agent lưu ảnh xuống đĩa theo đúng tên này; chỉ nhận đuôi ảnh quen thuộc để tên file
# không bao giờ mang theo ký tự đường dẫn từ tên gốc người dùng đặt.
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
DEFAULT_IMAGE_EXTENSION = ".jpg"

ROLE_LABELS = {"user": "Nhân viên", "assistant": "Trợ lý"}
# Agent trên máy lưu ảnh ra file cho Claude Code đọc bằng Read.
READ_IMAGE_NOTE = "(Ảnh đính kèm, đọc bằng Read: %s)"


def attachment_filename(attachment_id, original_name):
    """Tên file an toàn để agent lưu một ảnh đính kèm.

    Nhận: id attachment (int), tên gốc (chuỗi hoặc None).
    Trả: ``"anh_<id><đuôi>"``, đuôi lấy từ tên gốc nếu là đuôi ảnh quen thuộc.
    Biên: tên gốc rỗng / đuôi lạ -> đuôi ``.jpg``.
    """
    ext = os.path.splitext(original_name or "")[1].lower()
    if ext not in IMAGE_EXTENSIONS:
        ext = DEFAULT_IMAGE_EXTENSION
    return "anh_%d%s" % (int(attachment_id), ext)


def _message_body(message, image_note):
    """Nội dung một tin, đã bóc marker giả, kèm ghi chú ảnh nếu có."""
    text = strip_permission_markers(message.get("text"))
    files = message.get("attachments") or []
    if files:
        note = image_note % ", ".join(files)
        text = "%s\n%s" % (text, note) if text else note
    return text


def build_turn_prompt(new_messages, is_admin, history=None, image_note=READ_IMAGE_NOTE):
    """Gộp các tin sale vừa gửi thành một lượt cho Claude.

    Nhận:
        new_messages: list dict ``{'text': str, 'attachments': [tên file]}`` theo thứ tự.
        is_admin: người gửi có quyền quản lý không.
        history: list dict ``{'role': 'user'|'assistant', 'text': str}`` — chỉ truyền khi
            Claude mất phiên cũ và cần dựng lại ngữ cảnh.
        image_note: mẫu ghi chú ảnh, ``%s`` là danh sách tên file.
    Trả: chuỗi, LUÔN mở đầu bằng marker quyền (Claude chỉ tin marker ở đầu tin).
    Biên: không có tin nào có chữ -> chỉ còn marker.
    """
    parts = [_message_body(msg, image_note) for msg in new_messages]
    body = "\n".join(part for part in parts if part)

    if history:
        lines = [
            "%s: %s" % (ROLE_LABELS.get(item.get("role"), "?"), strip_permission_markers(item.get("text")))
            for item in history
        ]
        body = (
            "(Phiên làm việc trước bị ngắt. Dưới đây là các tin gần nhất để nắm lại ngữ cảnh; "
            "KHÔNG thực hiện lại lệnh tạo/sửa nào đã xong trong đó. Nếu tin mới là xác nhận "
            "cho đề xuất cuối cùng của Trợ lý thì làm tiếp như bình thường: quét trùng lại "
            "rồi tạo/sửa đúng đề xuất đó.)\n"
            + "\n".join(lines)
            + "\n\n(Tin mới của nhân viên:)\n"
            + body
        )
    return apply_permission_marker(body, is_admin)


def with_today(prompt, today):
    """Chèn ngày hôm nay ngay sau marker quyền ở đầu lượt.

    Claude không tự biết hôm nay là ngày nào, nên không nhận ra phiếu / PO đã quá ngày dự kiến.
    Nhận: prompt dạng ``"<marker> <nội dung>"`` (kết quả build_turn_prompt), today: ``date``.
    Trả: ``"<marker> (Hôm nay: dd/mm/yyyy) <nội dung>"`` — marker vẫn đứng đầu.
    Biên: prompt chỉ có marker -> ``"<marker> (Hôm nay: ...)"``; không có marker -> chèn ở đầu.
    """
    note = "(Hôm nay: %s)" % today.strftime("%d/%m/%Y")
    end = prompt.find("]") + 1 if prompt.startswith("[") else 0
    head, rest = prompt[:end], prompt[end:].strip()
    return " ".join(part for part in (head, note, rest) if part)
