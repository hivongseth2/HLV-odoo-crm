"""Chuẩn hoá địa chỉ giao hàng — hàm thuần, vào gì ra nấy.

Mục đích duy nhất: biến một chuỗi địa chỉ người gõ tay thành KHOÁ so khớp, để cùng một
địa chỉ viết khác nhau vẫn tra được cùng một bản ghi toạ độ đã lưu. Mỗi lần tra trượt là
một lượt gọi Google phải trả tiền cho thứ đã biết câu trả lời.

Địa chỉ trên phiếu giao là ô chữ tự do, nên cùng một chỗ có thể xuất hiện dưới dạng:
    "260/49 Nguyễn Thái Sơn, P.5, Gò Vấp, TP.HCM"
    "260/49 nguyen thai son, phuong 5, go vap, tphcm"
    "260/49  Nguyễn Thái Sơn , P5 , Gò Vấp , TP HCM"
Cả ba phải ra cùng một khoá.
"""

import re
import unicodedata

# Viết tắt hành chính hay gặp trên phiếu giao, quy về một dạng trước khi bỏ ký tự đặc
# biệt. Không quy thì "P.5" và "Phường 5" thành hai khoá khác nhau và cache trượt.
# Thứ tự quan trọng: cụm dài đứng trước để "tp hcm" không bị "tp" ăn mất một nửa.
_ABBREVIATIONS = (
    (r'\btp\.?\s*hcm\b', 'ho chi minh'),
    (r'\bt\.?p\.?\s*ho\s*chi\s*minh\b', 'ho chi minh'),
    (r'\bsai\s*gon\b', 'ho chi minh'),
    (r'\bha\s*noi\b', 'ha noi'),
    (r'\bq\.?\s*(\d+)\b', r'quan \1'),
    (r'\bp\.?\s*(\d+)\b', r'phuong \1'),
    (r'\bf\.?\s*(\d+)\b', r'phuong \1'),
    (r'\bkcn\b', 'khu cong nghiep'),
    (r'\bkdc\b', 'khu dan cu'),
    (r'\btt\b', 'thi tran'),
    (r'\btx\b', 'thi xa'),
    (r'\bh\.\s*', 'huyen '),
    (r'\bx\.\s*', 'xa '),
    (r'\bd\.\s*', 'duong '),
    (r'\bduong\s+so\s+(\d+)\b', r'duong \1'),
    (r'\bvn\b', 'viet nam'),
)

_NON_KEY_RE = re.compile(r'[^a-z0-9]+')
_SPACE_RE = re.compile(r'\s+')


def strip_accents(value):
    """Bỏ dấu tiếng Việt, giữ nguyên chữ cái. None/rỗng trả về chuỗi rỗng.

    Lặp lại ``hlv_geo_utils.tools.geo_text.strip_accents`` một cách có ý thức: file này
    phải chạy được mà không cần Odoo (để test bằng python trần), còn addon kia chỉ nạp
    được trong môi trường Odoo. Đây là 4 dòng chuẩn hoá Unicode, không phải quy tắc
    nghiệp vụ — lặp nó không sinh ra hai cách hiểu khác nhau về một luật.
    """
    if not value:
        return ''
    decomposed = unicodedata.normalize('NFD', str(value))
    without_marks = ''.join(c for c in decomposed if unicodedata.category(c) != 'Mn')
    return without_marks.replace('đ', 'd').replace('Đ', 'D')


def normalize_address(value):
    """Địa chỉ ở dạng ĐỌC ĐƯỢC đã chuẩn hoá: thường, không dấu, viết tắt đã mở rộng.

    Giữ khoảng trắng và dấu phẩy để còn đọc được khi soát lỗi. Dùng cái này khi gửi đi
    tra toạ độ; dùng ``address_key`` khi so khớp trong cache.

    Rỗng/None trả về chuỗi rỗng.
    """
    text = strip_accents(value).lower()
    if not text:
        return ''
    # Dấu chấm và phẩy đứng sát chữ làm hỏng biên từ \b, tách ra trước khi mở viết tắt.
    text = re.sub(r'([.,])', r'\1 ', text)
    for pattern, replacement in _ABBREVIATIONS:
        text = re.sub(pattern, replacement, text)
    text = text.replace(',', ' , ')
    text = _SPACE_RE.sub(' ', text).strip()
    return re.sub(r'\s*,\s*', ', ', text).strip(' ,')


def address_key(value):
    """Khoá so khớp của một địa chỉ: chỉ chữ thường và số, không khoảng trắng.

    Bỏ luôn dấu phẩy và khoảng trắng để "P.5, Gò Vấp" và "phuong 5 go vap" cùng ra một
    khoá. Trả về chuỗi rỗng khi không có gì để so — caller phải coi khoá rỗng là "không
    tra cache được", đừng lưu bản ghi với khoá rỗng.
    """
    return _NON_KEY_RE.sub('', normalize_address(value))
