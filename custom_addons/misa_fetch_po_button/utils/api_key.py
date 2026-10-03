# -*- coding: utf-8 -*-
"""So khớp API key của bên ngoài gọi vào.

Util thuần: vào hai chuỗi, ra True/False. Không đụng ``self.env``.
"""
import hmac
import re

# Key dán qua Zalo / Excel / trình soạn thảo hay dính ký tự vô hình ở đầu cuối.
_INVISIBLE = re.compile(r"[​-‍﻿]")


def _clean(value):
    return _INVISIBLE.sub("", str(value or "")).strip()


def api_key_matches(provided, expected):
    """Key gửi lên có đúng key đã cấu hình không.

    Nhận: key trong request, key cấu hình (có thể None).
    Trả: True nếu khớp. So sánh thời gian hằng để không lộ key qua độ trễ phản hồi.
    Biên: key cấu hình rỗng -> LUÔN False (chưa cấu hình là khoá cửa, không phải mở cửa);
        key gửi lên rỗng -> False.
    """
    expected = _clean(expected)
    provided = _clean(provided)
    if not expected or not provided:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))
