"""So khớp từ khoá / alias cho ô tìm tin nhắn (drawer điều phối + /sale_plan).

Vì sao cần lọc lại bằng Python: DB trên Odoo.sh bật `unaccent`, nên domain `ilike`
bỏ dấu cả hai vế — gõ "dạ" khớp mọi chữ "da" ("Đặng", "đang", "đặt"...). SQL vẫn
dùng để lọc thô (nhanh, có index), còn các hàm dưới đây quyết định cuối cùng.

Quy ước: từ gõ CÓ dấu thì khớp đúng dấu; từ gõ KHÔNG dấu thì khớp mọi dấu (giữ
tiện lợi gõ không dấu, đó chính là việc unaccent đã làm ở SQL).
"""

import unicodedata


def _fold(text):
    """Chữ thường + chuẩn hoá NFC (tin dán từ Zalo/Word hay ở dạng tổ hợp NFD)."""
    return unicodedata.normalize('NFC', text or '').lower()


def split_search_words(search):
    """Tách ô tìm thành các từ, mỗi từ là một điều kiện AND.

    Nhận: chuỗi người dùng gõ. Trả: list từ đã chữ thường + NFC, bỏ trùng, giữ thứ
    tự. Chuỗi rỗng / chỉ khoảng trắng → [].
    """
    words = []
    for word in _fold(search).split():
        if word not in words:
            words.append(word)
    return words


def has_accent(word):
    """True nếu từ có ký tự ngoài ASCII (có dấu, hoặc chữ đ)."""
    return any(ord(ch) > 127 for ch in word or '')


def needs_exact_check(words, aliases):
    """Có cần lọc lại bằng Python không: có từ có dấu, hoặc có alias.

    Alias luôn kiểm lại vì '@trâm bc' qua unaccent cũng khớp '@tram bc'.
    """
    return bool(aliases) or any(has_accent(w) for w in words)


def matches_words(words, texts):
    """Mỗi từ CÓ dấu phải xuất hiện đúng dấu trong ít nhất một chuỗi của texts.

    Nhận: words (từ split_search_words), texts (nội dung, người gửi, mã đơn, khách;
    None được bỏ qua). Trả: bool. Từ không dấu luôn coi là khớp (SQL đã lọc).
    words rỗng → True.
    """
    folded = [_fold(t) for t in texts if t]
    return all(
        any(word in text for text in folded)
        for word in words if has_accent(word)
    )


def mentions_all_aliases(text, aliases):
    """Nội dung tin có nhắc ĐỦ mọi alias (dạng '@alias', đúng dấu) không.

    Nhận: text (plain text của tin), aliases (đã chuẩn hoá chữ thường, không '@').
    Trả: bool. aliases rỗng → True.
    """
    folded = _fold(text)
    return all('@' + _fold(alias) in folded for alias in aliases)
