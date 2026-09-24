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
    # Quận/phường mang TÊN chứ không mang số ("Q. Phú Nhuận"). Đặt sau các luật trên để
    # không ăn mất trường hợp có số. Đòi có dấu chấm để không nuốt nhầm một từ bắt đầu
    # bằng q/p trong tên đường.
    (r'\bq\.\s*', 'quan '),
    (r'\bp\.\s*', 'phuong '),
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

# Cụm mở đầu bằng tiền tố pháp nhân là TÊN KHÁCH, không phải địa chỉ. Odoo ghép tên vào
# đầu `contact_address`, mà tên công ty gửi cho geocoder chỉ làm nhiễu: nhà cung cấp đi
# tìm doanh nghiệp cùng tên ở nơi khác thay vì tìm con đường đang hỏi.
_COMPANY_SEGMENT_RE = re.compile(
    r'^(?:'
    r'cong\s*ty|cty|c\.?\s*ty|congty'
    r'|chi\s*nhanh|nha\s*may|van\s*phong\s*dai\s*dien'
    r'|doanh\s*nghiep\s*tu\s*nhan|dntn'
    r'|co\.?,?\s*ltd|ltd|jsc|corp|corporation'
    r')\b'
)


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


def normalize_address(value, drop_company=True):
    """Địa chỉ ở dạng ĐỌC ĐƯỢC đã chuẩn hoá: thường, không dấu, viết tắt đã mở rộng,
    **đã bỏ cụm lặp và bỏ tên công ty**.

    Đây là chuỗi gửi đi tra toạ độ. Bản nguyên văn vẫn được giữ ở ô "Địa chỉ gốc" để đối
    chiếu, nên ở đây cắt gọn được thoải mái.

    Vì sao phải khử lặp: ``contact_address`` của Odoo ghép tên khách + street + street2 +
    city + state + country, mà người nhập thường đã gõ đủ tỉnh/huyện vào ô street. Kết quả
    là chuỗi kiểu::

        CÔNG TY ... DONGJIN TEXTILE VINA, Huyện Nhơn Trạch, Đồng Nai, Việt Nam, ,
        Đồng Nai, Đồng Nai Việt Nam

    — "Đồng Nai" ba lần, "Việt Nam" hai lần, một cụm rỗng. Gửi nguyên chuỗi đó đi thì
    geocoder khớp kém hẳn so với chuỗi sạch.

    ``drop_company=False`` giữ lại cụm tên công ty — dùng khi tra bằng Google, vì Google
    tra được cả tên doanh nghiệp.

    Rỗng/None trả về chuỗi rỗng.
    """
    text = strip_accents(value).lower()
    if not text:
        return ''
    # Dấu chấm và phẩy đứng sát chữ làm hỏng biên từ \b, tách ra trước khi mở viết tắt.
    text = re.sub(r'([.,])', r'\1 ', text)
    for pattern, replacement in _ABBREVIATIONS:
        text = re.sub(pattern, replacement, text)
    text = _SPACE_RE.sub(' ', text)

    segments = [seg.strip(' .') for seg in text.split(',')]
    return ', '.join(_clean_segments(segments, drop_company))


def _clean_segments(segments, drop_company):
    """Bỏ cụm rỗng, cụm tên công ty, cụm trùng và cụm đã nằm trong một cụm khác.

    Giữ thứ tự xuất hiện: cụm đầu thường là số nhà và tên đường — thứ geocoder cần nhất.

    Làm hai pha chứ không gộp một vòng: gộp một vòng thì cụm bị thay thế ở giữa chừng vẫn
    để lại những cụm ngắn đã trót giữ trước đó ("viet nam" nằm lại sau khi "dong nai" được
    nâng thành "dong nai viet nam").
    """
    kept = [
        segment for segment in segments
        if segment and not (drop_company and _COMPANY_SEGMENT_RE.match(segment))
    ]
    # Pha 2: cụm nào đã nằm trọn trong một cụm khác thì bỏ, giữ cụm DÀI hơn vì nó mang
    # nhiều thông tin hơn.
    result = []
    for segment in kept:
        if any(segment != other and segment in other for other in kept):
            continue
        if segment not in result:
            result.append(segment)
    return result


def address_key(value):
    """Khoá so khớp của một địa chỉ: chỉ chữ thường và số, không khoảng trắng.

    Bỏ luôn dấu phẩy và khoảng trắng để "P.5, Gò Vấp" và "phuong 5 go vap" cùng ra một
    khoá. Trả về chuỗi rỗng khi không có gì để so — caller phải coi khoá rỗng là "không
    tra cache được", đừng lưu bản ghi với khoá rỗng.
    """
    return _NON_KEY_RE.sub('', normalize_address(value))
