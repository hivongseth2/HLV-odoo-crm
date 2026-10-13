# -*- coding: utf-8 -*-
"""Hàm thuần đọc gói tin máy nghe Zalo gửi lên — không đụng env, không side effect."""

from datetime import datetime, timezone

# Loại tin hiển thị trong Odoo. Zalo đặt msgType dạng "webchat", "chat.photo", "share.file", "chat.voice"…
# và không công bố danh sách đủ, nên đoán theo chữ trong msgType; lạ thì "other" (vẫn lưu msg_type gốc).
MESSAGE_KINDS = [
    ("text", "Chữ"),
    ("image", "Ảnh"),
    ("file", "File"),
    ("voice", "Ghi âm"),
    ("video", "Video"),
    ("sticker", "Sticker"),
    ("link", "Link"),
    ("other", "Khác"),
]
_KIND_HINTS = (
    ("sticker", "sticker"),
    ("photo", "image"),
    ("gif", "image"),
    ("voice", "voice"),
    ("video", "video"),
    ("file", "file"),
    ("link", "link"),
    ("recommended", "link"),
)

# Biểu tượng thả cảm xúc hay gặp → chữ dễ đọc; mã lạ giữ nguyên.
REACTION_LABELS = {
    "/-heart": "❤️",
    "/-strong": "👍",
    "/-weak": "👎",
    "/-ok": "👌",
    ":>": "😆",
    ":o": "😮",
    ":-((": "😢",
    ":-h": "😡",
    "_()_": "🙏",
    "/-thanks": "🙏 cảm ơn",
}


def message_kind(msg_type, has_attachment):
    """Loại tin từ msgType gốc của Zalo.

    Nhận: msg_type (chuỗi, có thể None), has_attachment (tin có link tải ảnh / file).
    Trả: một mã trong MESSAGE_KINDS. "webchat" / rỗng mà không có đính kèm → "text"; msgType lạ có đính kèm → "file";
    lạ không đính kèm → "other".
    """
    value = (msg_type or "").lower()
    for hint, kind in _KIND_HINTS:
        if hint in value:
            return kind
    if value in ("", "webchat"):
        return "file" if has_attachment else "text"
    return "file" if has_attachment else "other"


def ts_to_utc(ts_ms):
    """Mốc thời gian Zalo (mili giây, số hoặc chuỗi) → datetime UTC không múi giờ (cách Odoo lưu Datetime).

    Trống / không phải số / ngoài khoảng hợp lệ → None.
    """
    try:
        seconds = int(str(ts_ms).strip()) / 1000.0
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None


def clean_id(value):
    """Mã Zalo (uid, mã nhóm, mã tin) về chuỗi gọn; None / rỗng → ""."""
    if value is None:
        return ""
    return str(value).strip()


def clip(text, limit):
    """Cắt chuỗi về tối đa limit ký tự (None → ""), để một gói lạ không phình DB."""
    return (text or "")[:limit] if isinstance(text, str) else ""


def reaction_label(icon):
    """Mã cảm xúc Zalo ("/-heart") → biểu tượng dễ đọc; mã lạ / rỗng giữ nguyên."""
    return REACTION_LABELS.get(icon or "", icon or "")
