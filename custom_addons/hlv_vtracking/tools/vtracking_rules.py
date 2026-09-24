"""Đọc file luật khách của bộ điều phối chạy tay -> giá trị cho Thói quen khách. Hàm thuần.

File nguồn (`khach.json`) do người điều phối ghi bằng tay suốt quá trình chạy thật: mỗi lần
xe bị chặn ở cổng, mỗi lần khách từ chối nhận sau 16h, họ ghi thêm một dòng. Đây là tri
thức đắt nhất của kho — nhưng nó nằm ngoài Odoo và **không được đưa vào mã nguồn**: đó là
danh sách khách hàng thật.

File này chỉ lo phần ĐỌC và DIỄN GIẢI: vào một dict JSON, ra danh sách đề xuất. Việc tìm
điểm khớp và ghi vào cơ sở dữ liệu nằm ở ``models/vtracking_rule_import.py``.

Không đụng ``self.env``, không đọc file, không ghi gì.
"""

import re
import unicodedata

# Tiền tố pháp nhân: bỏ đi thì mới so được tên. Sắp từ DÀI tới NGẮN — "công ty tnhh một
# thành viên" phải khớp trước "công ty tnhh", nếu không chỉ cắt được một nửa.
COMPANY_PREFIXES = (
    'cong ty trach nhiem huu han mot thanh vien',
    'cong ty trach nhiem huu han',
    'chi nhanh cong ty tnhh',
    'chi nhanh cong ty',
    'cong ty tnhh mot thanh vien',
    'cong ty tnhh mtv',
    'cong ty co phan',
    'cong ty tnhh',
    'doanh nghiep tu nhan',
    'cong ty cp',
    'chi nhanh',
    'cong ty',
    'cty tnhh',
    'cty',
)

# Nhóm cờ trong file -> ô trên Thói quen khách.
FLAG_FIELDS = {
    'thong_quan': ('procedure_required', 'customs'),
    'dang_ky': ('procedure_required', 'register'),
    'tu_ghe': ('delivery_method', 'pickup'),
    'cpn': ('delivery_method', 'express'),
    'cuoi_chuyen': ('must_be_last', True),
}
# Nhóm chỉ ghi chú, không có ô riêng — đừng bịa ra ô mới cho chúng.
NOTE_FLAGS = {
    'ngoai_tuyen': 'Ngoài tuyến xe Bến Cam.',
    'tien_duong': 'Nhân viên tiện đường đem về giao, không đi xe chuyến.',
}

# "CHƯA BAO GIỜ nhận sau 16:00 (0/38)" -> receiving_to = 16.0
NEVER_AFTER = re.compile(r'kh[ôo]ng nh[ậa]n sau\s*(\d{1,2})[:h](\d{2})|'
                         r'ch[ưu]a bao gi[ờo] nh[ậa]n sau\s*(\d{1,2})[:h](\d{2})',
                         re.IGNORECASE)
# Định mức đứng của một điểm một phiếu — phần dôi ra mới ghi vào "phút lâu hơn thường lệ".
BASE_SERVICE_MINUTES = 4


def normalize(name):
    """Tên khách -> khoá so sánh: bỏ dấu, bỏ tiền tố pháp nhân, gộp khoảng trắng.

    "CÔNG TY TNHH Cáp điện & Hệ thống LS Việt Nam" -> "cap dien he thong ls viet nam".
    Trả chuỗi rỗng khi không còn gì để so.
    """
    text = unicodedata.normalize('NFD', name or '')
    text = ''.join(ch for ch in text if unicodedata.category(ch) != 'Mn')
    text = text.replace('đ', 'd').replace('Đ', 'D').lower()
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    for prefix in COMPANY_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    return text


def parse_hour(text):
    """"16:00" trong câu luật -> 16.0. Không thấy giờ thì None."""
    match = NEVER_AFTER.search(text or '')
    if not match:
        return None
    hour, minute = (match.group(1), match.group(2)) if match.group(1) else (match.group(3),
                                                                           match.group(4))
    return int(hour) + int(minute) / 60.0


def _merge_procedure(current, new):
    """Khách vừa phải thông quan vừa phải đăng ký thì là 'both' — không phải cái sau đè cái
    trước. Đây là lỗi thật đã có: Jabil cần CẢ HAI, bỏ một cái là xe đi rồi bị chặn."""
    if not current or current == new:
        return new
    return 'both'


def rules_from_file(data):
    """Nội dung ``khach.json`` -> list đề xuất, mỗi khách một mục.

    :param data: dict đã ``json.loads``
    :returns: list dict ``{'name', 'key', 'values', 'notes'}`` sắp theo tên —
        ``values`` là các ô sẽ ghi vào Thói quen khách, ``notes`` là câu giải thích kèm mã
        luật để người duyệt biết vì sao.

    Chỉ diễn giải những gì có ô tương ứng. Luật không ánh xạ được (ví dụ "bỏ qua nếu đơn
    nhỏ và sales không giục") vẫn được giữ nguyên văn trong ghi chú cho tài xế — mất chúng
    còn tệ hơn là để người đọc tự hiểu.
    """
    found = {}

    def entry(name):
        key = normalize(name)
        if not key:
            return None
        return found.setdefault(key, {'name': name, 'key': key, 'values': {}, 'notes': []})

    for flag, (field, value) in FLAG_FIELDS.items():
        for name in data.get(flag) or []:
            item = entry(name)
            if not item:
                continue
            if field == 'procedure_required':
                item['values'][field] = _merge_procedure(item['values'].get(field), value)
            else:
                item['values'][field] = value

    for flag, note in NOTE_FLAGS.items():
        for name in data.get(flag) or []:
            item = entry(name)
            if item:
                item['notes'].append(note)

    for name, minutes in (data.get('dung_rieng') or {}).items():
        item = entry(name)
        if item:
            extra = max(int(minutes) - BASE_SERVICE_MINUTES, 0)
            item['values']['extra_service_minutes'] = extra
            item['notes'].append('Đứng tại điểm ~%s phút (đo thực tế).' % minutes)

    for rule in data.get('luat') or []:
        item = entry(rule.get('khach') or '')
        if not item:
            continue
        text = (rule.get('luat') or '').strip()
        hour = parse_hour(text)
        if hour is not None:
            item['values']['receiving_to'] = hour
        item['notes'].append('[%s] %s' % (rule.get('id') or '?', text))

    return sorted(found.values(), key=lambda item: item['name'].lower())


def note_text(notes, source):
    """Các câu ghi chú -> một khối chữ, có ghi rõ lấy từ đâu.

    Ghi nguồn là bắt buộc: sáu tháng nữa không ai nhớ dòng "phải là điểm cuối" đến từ đâu,
    và không biết nguồn thì không ai dám sửa.
    """
    lines = [note for note in notes if note]
    if not lines:
        return ''
    return '\n'.join(lines + ['— nguồn: %s' % source])


def alias_map(data):
    """Bí danh -> tên chuẩn, cả hai đã chuẩn hoá.

    File nguồn có sẵn bảng này vì Odoo và bản đồ ghi tên khác nhau ("Serverone" với
    "Serveone", "Jabil - JTV Nhơn Trạch" với "Jabil"). Dùng khi tìm điểm khớp: không có nó
    thì mấy khách hay bị ghi sai tên sẽ không khớp được điểm nào.
    """
    result = {}
    for alias, real in (data.get('bi_danh') or {}).items():
        key, target = normalize(alias), normalize(real)
        if key and target:
            result[key] = target
    return result


# Từ quá phổ biến, có mặt ở hàng chục tên nên không giúp phân biệt ai với ai.
STOPWORDS = frozenset(('viet', 'nam', 'vietnam', 'vina', 'co', 'ltd', 'jsc', 'group',
                       'industries', 'industry', 'international', 'quoc', 'te'))


def keywords(key):
    """Các từ đáng dùng để so tên. Bỏ từ quá phổ biến và từ một ký tự."""
    return {word for word in (key or '').split()
            if len(word) > 1 and word not in STOPWORDS}


def match_keys(key, place_keys, aliases=None):
    """Tên khách trong file -> các khoá tên địa điểm có thể là khách đó.

    :param key: tên đã chuẩn hoá của khách trong file
    :param place_keys: iterable các khoá tên địa điểm (đã chuẩn hoá)
    :param aliases: bảng bí danh đã chuẩn hoá
    :returns: list khoá, khớp chắc chắn đứng trước

    Khớp theo TỪ chứ không theo chuỗi con: Odoo ghi "CÁP ĐIỆN VÀ HỆ THỐNG LS VIỆT NAM" còn
    file ghi "Cáp điện & Hệ thống LS" — chỉ hơn nhau chữ "và", nhưng so chuỗi con là trượt.

    Bỏ các từ quá phổ biến (Việt Nam, Vina, Co, Ltd) trước khi so: giữ chúng thì "Nam Hoa"
    khớp luôn "Bao bì Nam Việt", đúng cái bẫy mà người điều phối đã ghi lại.
    """
    aliases = aliases or {}
    place_keys = list(place_keys)
    for candidate in (key, aliases.get(key)):
        if candidate and candidate in place_keys:
            return [candidate]

    wanted = keywords(key)
    if not wanted:
        return []
    hits = []
    for place_key in place_keys:
        found = keywords(place_key)
        if found and (wanted <= found or found <= wanted):
            hits.append(place_key)
    return hits
