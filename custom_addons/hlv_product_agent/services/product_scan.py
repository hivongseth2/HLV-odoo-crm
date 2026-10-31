# -*- coding: utf-8 -*-
"""Quét tên sản phẩm theo điều kiện Claude tự đặt (tool quet_san_pham).

Khác tim_hang_tuong_tu: không xếp hạng, không cắt theo số bán — trả ĐỦ mọi mã khớp, để sale hỏi
"tất cả máy X" không bị sót mã bán chậm. Claude tự đặt điều kiện chặt (tên bắt đầu bằng loại hàng,
hãng, không chứa "dùng cho"...) như người lọc tay.

Util thuần: vào chuỗi / list, ra bool / dict. Không đụng ``self.env``.
"""
from .query_format import squash_text

# Quá ngần này mã thì bắt thêm điều kiện thay vì trả cả đống (tốn token, sale cũng không đọc hết).
MAX_SCAN_RESULTS = 100
MAX_SCAN_TERMS = 8
# Cụm 2 ký tự là chuyện thường ở đây: "co", "tê", "ốc", quy cách "60", "m8". Không như từ khoá của
# tim_hang_tuong_tu (chặn "HD" khớp mọi thứ): bat_dau đã khoanh theo đầu tên nên không nhiễu.
MIN_SCAN_CHARS = 2


def scan_terms(values):
    """Các cụm điều kiện đã chuẩn hoá để so, bỏ cụm quá ngắn.

    Nhận: chuỗi hoặc list chuỗi. Trả: list chuỗi đã squash_text, giữ thứ tự, bỏ trùng, tối đa
    MAX_SCAN_TERMS. Biên: None / phần tử không phải chuỗi / ngắn hơn MIN_SCAN_CHARS -> bỏ.
    """
    if isinstance(values, str):
        values = [values]
    result = []
    for value in values or []:
        key = squash_text(value) if isinstance(value, str) else ""
        if len(key) >= MIN_SCAN_CHARS and key not in result:
            result.append(key)
    return result[:MAX_SCAN_TERMS]


def with_aliases(terms, aliases):
    """Thêm tên loại kho ứng với các cách gọi sale dùng vào danh sách cụm bat_dau.

    Nhận: list cụm đã chuẩn hoá, aliases = {cách gọi đã chuẩn hoá: [tên loại kho đã chuẩn hoá]}
    (bảng hlv.product.name.alias). Trả: list mới, tên loại kho đứng ngay sau cụm gốc, bỏ trùng.
    Biên: aliases rỗng / không có cụm nào trong bảng -> giữ nguyên.
    """
    result = []
    for term in terms:
        result.append(term)
        result += aliases.get(term, [])
    return list(dict.fromkeys(result))


def scan_criteria(args, aliases=None):
    """Điều kiện quét từ tham số tool.

    Nhận: dict tham số (bat_dau, chua, khong_chua, hang, ma_chua), aliases như with_aliases. Trả: dict
    cùng khoá, mỗi khoá là list cụm đã chuẩn hoá; bat_dau đã thêm tên loại kho. Biên: thiếu khoá /
    sai kiểu -> list rỗng.
    """
    args = args if isinstance(args, dict) else {}
    criteria = {key: scan_terms(args.get(key)) for key in ('bat_dau', 'chua', 'khong_chua', 'hang', 'ma_chua')}
    criteria['bat_dau'] = with_aliases(criteria['bat_dau'], aliases or {})
    return criteria


def has_scan_filter(criteria):
    """Có điều kiện nào thu hẹp được danh sách không (chỉ khong_chua / hang thì quá rộng)."""
    return bool(criteria['bat_dau'] or criteria['chua'] or criteria['ma_chua'])


def scan_match(criteria, name, code):
    """Một sản phẩm có khớp điều kiện quét không.

    Nhận: criteria (từ scan_criteria), name, code. Trả: bool.
    Luật: tên bắt đầu bằng MỘT trong bat_dau (nếu có); tên hoặc mã chứa MỌI cụm chua; tên không
    chứa cụm nào trong khong_chua; tên hoặc mã chứa MỘT trong hang (nếu có); mã chứa MỘT trong
    ma_chua (nếu có). So không dấu, bỏ khoảng trắng / ký tự: "bu lông" = "bulong".
    Biên: criteria không có điều kiện nào -> True.
    """
    name_key, code_key = squash_text(name), squash_text(code)
    both = name_key + " " + code_key
    if criteria['bat_dau'] and not any(name_key.startswith(term) for term in criteria['bat_dau']):
        return False
    if not all(term in both for term in criteria['chua']):
        return False
    if any(term in name_key for term in criteria['khong_chua']):
        return False
    if criteria['hang'] and not any(term in both for term in criteria['hang']):
        return False
    if criteria['ma_chua'] and not any(term in code_key for term in criteria['ma_chua']):
        return False
    return True
