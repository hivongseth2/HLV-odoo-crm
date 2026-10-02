# -*- coding: utf-8 -*-
"""So khớp tên tiếng Việt do người (hoặc AI) gõ với tên lưu trên MISA.

Util thuần: vào chuỗi, ra chuỗi. Không đụng ``self.env``, không side effect.

Lý do tồn tại: tên nhóm hàng trên MISA do người nhập, còn tên đi tìm thì do người gõ
tay hoặc do AI đọc từ tài liệu. Hai bên lệch nhau ở dấu cách và dấu tiếng Việt là
chuyện thường — "Bulong máy" với "Bu lông máy" là cùng một nhóm, nhưng so bằng dấu
bằng thì trượt.
"""
import re
import unicodedata

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def normalize_vn(text):
    """Rút một tên tiếng Việt về dạng chỉ còn chữ thường và số, bỏ dấu.

    Nhận: chuỗi bất kỳ hoặc None.
    Trả: chuỗi đã bỏ dấu tiếng Việt, bỏ mọi khoảng trắng và ký tự ngăn cách.
    Biên: None hoặc chuỗi toàn ký tự đặc biệt -> "".

    Ví dụ: "Bu lông máy", "Bulong máy", "BU-LONG-MAY" -> đều ra "bulongmay".
    """
    if not text:
        return ""
    # đ/Đ không tách được bằng NFD nên phải thay tay trước.
    text = str(text).replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", text)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _NON_ALNUM_RE.sub("", without_marks.lower())


def same_name(left, right):
    """Hai tên có cùng chỉ một thứ không, bỏ qua khác biệt dấu và khoảng trắng.

    Nhận: hai chuỗi bất kỳ hoặc None.
    Trả: True/False.
    Biên: một trong hai rỗng -> False (không coi rỗng là khớp với rỗng).
    """
    left_key = normalize_vn(left)
    return bool(left_key) and left_key == normalize_vn(right)
