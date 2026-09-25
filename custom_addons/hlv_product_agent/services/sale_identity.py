# -*- coding: utf-8 -*-
"""Tách danh sách sale dùng chung một tài khoản Odoo.

Util thuần: vào hai chuỗi, ra list dict. Không đụng ``self.env``.

Nhiều sale dùng chung một tài khoản; tài khoản khai sẵn hai field cùng thứ tự:
    x_misa_saler_codes        = "MAIVANNAM1,HUYNHTHIMYPHUONG,LUUTHICONG1"
    x_sale_plan_mention_names = "Nam ĐN,Phương ĐN,Công ĐN"
Phần tử thứ i của field này là cùng một người với phần tử thứ i của field kia.
"""


def _split(raw):
    return [part.strip() for part in (raw or '').split(',')]


def parse_sale_identities(codes_raw, names_raw):
    """Ghép mã sale MISA với tên theo vị trí.

    Nhận: chuỗi mã, chuỗi tên (phân tách bằng dấu phẩy, có thể None).
    Trả: list dict ``{'key', 'code', 'name'}`` theo thứ tự khai, không trùng key.
        ``key`` là mã (in hoa) nếu có, không thì là tên — dùng để phân biệt cuộc chat.
    Biên:
        - hai danh sách dài ngắn khác nhau -> ghép tới hết danh sách dài hơn; thiếu tên
          thì lấy mã làm tên, thiếu mã thì code rỗng;
        - vị trí có cả mã lẫn tên đều rỗng -> bỏ qua;
        - cả hai chuỗi rỗng -> [].
    """
    codes = _split(codes_raw)
    names = _split(names_raw)
    result = []
    seen = set()
    for index in range(max(len(codes), len(names))):
        code = codes[index] if index < len(codes) else ''
        name = names[index] if index < len(names) else ''
        if not code and not name:
            continue
        key = code.upper() if code else name
        if key in seen:
            continue
        seen.add(key)
        result.append({'key': key, 'code': code, 'name': name or code})
    return result


def resolve_sale_identity(identities, sale_key):
    """Chọn người đang chat trong danh sách sale của tài khoản.

    Nhận: kết quả parse_sale_identities, key trình duyệt gửi lên (có thể rỗng).
    Trả: ``(identity, required)``:
        - tài khoản 0-1 người: ``(người đó hoặc None, False)`` — không cần hỏi;
        - nhiều người, key hợp lệ: ``(người đó, True)``;
        - nhiều người, key rỗng / không có trong danh sách: ``(None, True)`` — phải hỏi.
    """
    if len(identities) <= 1:
        return (identities[0] if identities else None), False
    for identity in identities:
        if sale_key and identity['key'] == sale_key:
            return identity, True
    return None, True
