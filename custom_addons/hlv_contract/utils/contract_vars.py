# -*- coding: utf-8 -*-
"""Biến của mẫu hợp đồng: loại biến, thư viện biến chuẩn, định dạng giá trị.

Ba loại biến trong một mẫu:
- Biến tự điền (SYSTEM): module tự tính — số hợp đồng, ngày ký, bên bán (cấu hình công
  ty), bảng hàng (Ten_Hang_1, DVT_1...) và tổng tiền. Người dùng không nhập.
- Biến nhập (mọi tên còn lại): mỗi mẫu tự khai (hlv.contract.template.variable), người
  dùng điền trên hợp đồng. Thư viện STANDARD_VARIABLES chỉ là gợi ý nhãn/kiểu cho các tên
  hay dùng (bên mua, điều khoản) và cho biết biến nào tự điền được khi chọn khách hàng.

Tên biến giữ như form Excel + mẫu Word cũ (Ten_Ben_Mua, Don_Gia_1...) để mẫu cũ chạy được.
"""

import re
import unicodedata
from decimal import Decimal, ROUND_HALF_UP

from .amount_words import amount_in_words_vi

# Số dòng hàng có sẵn trong mẫu Word gốc; dùng cho số cột Excel tối thiểu
LINE_COUNT = 10

DATE_VARIABLES = ['So_Hop_Dong', 'Ngay_Ky', 'Thang_Ky', 'Nam_Ky']
TOTAL_VARIABLES = ['Tong_Tien_Hang', 'Thue_Suat_VAT', 'Tien_Thue_VAT', 'Tong_Gia_Tri_HD', 'Tong_Gia_Tri_Bang_Chu']
SELLER_VARIABLES = [
    'Ten_Ben_Ban', 'Dia_Chi_Ben_Ban', 'Dien_Thoai_Ben_Ban', 'Ma_So_Thue_Ben_Ban',
    'Nguoi_Dai_Dien_Ben_Ban', 'Chuc_Vu_Ben_Ban', 'Tai_Khoan_Ben_Ban', 'Ngan_Hang_Ben_Ban',
]
LINE_FIELDS = ['Ten_Hang', 'DVT', 'So_Luong', 'Don_Gia', 'Thanh_Tien']
LINE_VARIABLE_RE = re.compile(r'^(%s)_(\d+)$' % '|'.join(LINE_FIELDS))
SYSTEM_VARIABLES = DATE_VARIABLES + SELLER_VARIABLES + TOTAL_VARIABLES

VARIABLE_TYPES = [('text', 'Chữ'), ('textarea', 'Đoạn văn'), ('number', 'Số'), ('money', 'Số tiền'), ('date', 'Ngày')]
SECTIONS = [('general', 'Thông tin chung'), ('buyer', 'Bên mua'), ('goods', 'Hàng hoá'), ('terms', 'Điều khoản'),
            ('other', 'Khác')]

# Thư viện biến hay dùng: tên -> (nhãn, kiểu, nhóm). Không bắt buộc mẫu nào phải có.
STANDARD_VARIABLES = {
    'Ten_Ben_Mua': ('Tên bên mua', 'text', 'buyer'),
    'Dia_Chi_Ben_Mua': ('Địa chỉ bên mua', 'text', 'buyer'),
    'Ma_So_Thue_Ben_Mua': ('Mã số thuế bên mua', 'text', 'buyer'),
    'Dien_Thoai_Ben_Mua': ('Điện thoại bên mua', 'text', 'buyer'),
    'Fax_Ben_Mua': ('Fax bên mua', 'text', 'buyer'),
    'Nguoi_Dai_Dien_Ben_Mua': ('Người đại diện bên mua', 'text', 'buyer'),
    'Chuc_Vu_Ben_Mua': ('Chức vụ bên mua', 'text', 'buyer'),
    'Thoi_Gian_Giao_Hang': ('Thời gian giao hàng', 'text', 'terms'),
    'Dia_Diem_Giao_Hang': ('Địa điểm giao hàng', 'text', 'terms'),
    'Dieu_Kien_Thanh_Toan': ('Điều kiện thanh toán', 'textarea', 'terms'),
    'Mat_Hang_Chinh': ('Mặt hàng chính', 'text', 'goods'),
    'Ngay_Het_Han': ('Hiệu lực đến ngày', 'date', 'general'),
    'Toa_An_Giai_Quyet': ('Toà án giải quyết tranh chấp', 'text', 'terms'),
}

SYSTEM_LABELS = {
    'So_Hop_Dong': 'Số hợp đồng', 'Ngay_Ky': 'Ngày ký', 'Thang_Ky': 'Tháng ký', 'Nam_Ky': 'Năm ký',
    'Ten_Ben_Ban': 'Tên bên bán', 'Dia_Chi_Ben_Ban': 'Địa chỉ bên bán', 'Dien_Thoai_Ben_Ban': 'Điện thoại bên bán',
    'Ma_So_Thue_Ben_Ban': 'MST bên bán', 'Nguoi_Dai_Dien_Ben_Ban': 'Người đại diện bên bán',
    'Chuc_Vu_Ben_Ban': 'Chức vụ bên bán', 'Tai_Khoan_Ben_Ban': 'Số tài khoản bên bán',
    'Ngan_Hang_Ben_Ban': 'Ngân hàng bên bán',
    'Tong_Tien_Hang': 'Tổng tiền hàng', 'Thue_Suat_VAT': 'Thuế suất VAT (%)', 'Tien_Thue_VAT': 'Tiền thuế VAT',
    'Tong_Gia_Tri_HD': 'Tổng giá trị (sau VAT)', 'Tong_Gia_Tri_Bang_Chu': 'Tổng giá trị bằng chữ',
    'Ten_Hang_1': 'Tên hàng', 'DVT_1': 'Đơn vị tính', 'So_Luong_1': 'Số lượng',
    'Don_Gia_1': 'Đơn giá (chưa VAT)', 'Thanh_Tien_1': 'Thành tiền (chưa VAT)',
}


def is_system_variable(name):
    """True nếu module tự điền biến này (người dùng không phải nhập), kể cả dòng hàng số bất kỳ."""
    return name in SYSTEM_VARIABLES or bool(LINE_VARIABLE_RE.match(name or ''))


def is_line_variable(name):
    return bool(LINE_VARIABLE_RE.match(name or ''))


def default_variable_def(name):
    """Nhãn/kiểu/nhóm mặc định cho một biến nhập mới thấy trong mẫu: lấy theo thư viện,
    tên lạ thì nhãn là tên bỏ dấu gạch dưới ('Bao_Hanh' -> 'Bao Hanh'), kiểu chữ, nhóm Khác."""
    label, var_type, section = STANDARD_VARIABLES.get(name, (name.replace('_', ' '), 'text', 'other'))
    return {'name': name, 'label': label, 'var_type': var_type, 'section': section}


def variable_code(label):
    """Nhãn tiếng Việt -> tên biến: 'Thời hạn bảo hành' -> 'Thoi_Han_Bao_Hanh'.
    Bỏ dấu, đ -> d, chỉ giữ chữ/số; rỗng -> 'Bien'. Tên bắt đầu bằng số thì thêm 'Bien_'."""
    text = unicodedata.normalize('NFD', (label or '').replace('đ', 'd').replace('Đ', 'D'))
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    words = re.findall(r'[A-Za-z0-9]+', text)
    code = '_'.join(w[:1].upper() + w[1:].lower() for w in words) or 'Bien'
    return 'Bien_' + code if code[0].isdigit() else code


def format_money(amount):
    """Số tiền -> '39.476.160'. None/'' -> ''. Làm tròn nửa lên về đồng nguyên, cùng cách
    với amount_in_words_vi (round() của Python làm tròn kiểu ngân hàng: 1498,5 -> 1498)."""
    if amount in (None, ''):
        return ''
    value = int(Decimal(str(amount)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    return '{:,}'.format(value).replace(',', '.')


def format_number(number):
    """Số lượng/thuế suất -> '4' hoặc '7,5' (dấu phẩy thập phân kiểu Việt). Bỏ số 0 thừa."""
    if number in (None, ''):
        return ''
    value = float(number)
    if value.is_integer():
        return str(int(value))
    return ('%s' % round(value, 4)).rstrip('0').replace('.', ',')


def format_input(var_type, raw):
    """Giá trị người dùng nhập -> chữ in ra hợp đồng theo kiểu biến.
    date 'YYYY-MM-DD' -> 'dd/mm/yyyy'; money -> '1.250.000'; number -> '2,5'; còn lại giữ nguyên.
    Rỗng/None -> ''. Giá trị sai kiểu (gõ chữ vào ô số) thì in nguyên văn thay vì báo lỗi."""
    if raw in (None, '', False):
        return ''
    text = str(raw).strip()
    try:
        if var_type == 'date' and re.match(r'^\d{4}-\d{2}-\d{2}$', text):
            year, month, day = text.split('-')
            return '%s/%s/%s' % (day, month, year)
        if var_type == 'money':
            return format_money(float(text))
        if var_type == 'number':
            return format_number(float(text))
    except ValueError:
        return text
    return text


def price_excl(price_incl, vat_rate):
    """Giá sau VAT (người dùng gõ) -> giá chưa VAT (in trên hợp đồng). Không làm tròn: làm tròn
    ở đây thì tổng sau VAT lệch vài đồng so với số người dùng đã gõ."""
    return float(price_incl or 0) / (1 + float(vat_rate or 0) / 100)


def price_incl(price_unit, vat_rate):
    """Giá chưa VAT -> giá sau VAT để hiện lại cho người dùng."""
    return float(price_unit or 0) * (1 + float(vat_rate or 0) / 100)


def line_subtotal(quantity, price_unit):
    """Thành tiền một dòng = số lượng x đơn giá (chưa VAT); None/'' coi là 0."""
    return float(quantity or 0) * float(price_unit or 0)


def compute_totals(subtotals, vat_rate):
    """Tổng hợp đồng từ thành tiền từng dòng (chưa VAT) và thuế suất (%).
    Trả {'untaxed', 'vat', 'total', 'words'} đã làm tròn đồng, và vat = total - untaxed sau khi
    làm tròn để ba số in ra luôn cộng khớp. Danh sách rỗng -> 0 và "Không đồng"."""
    untaxed = sum(float(s or 0) for s in subtotals)
    total_exact = untaxed * (1 + float(vat_rate or 0) / 100)
    untaxed_r = int(Decimal(str(untaxed)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    total_r = int(Decimal(str(total_exact)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    return {'untaxed': untaxed_r, 'vat': total_r - untaxed_r, 'total': total_r,
            'words': amount_in_words_vi(total_r)}


def build_vars(system, inputs, input_types, lines, vat_rate):
    """Dict {tên biến: chữ in ra} cho fill_docx.

    system: {'So_Hop_Dong', 'Ngay_Ky' (datetime.date), biến bên bán...} — module tự có.
    inputs: {tên: giá trị thô} người dùng nhập; input_types: {tên: kiểu biến}.
    lines: list {'Ten_Hang','DVT','So_Luong','Don_Gia'} (không giới hạn số dòng).
    Biến nhập thiếu giá trị -> ''. Mẫu ít dòng hàng hơn thì docx_merge tự nhân bản dòng cuối.
    """
    out = {name: '' for name in SYSTEM_VARIABLES}
    for name, var_type in input_types.items():
        out[name] = format_input(var_type, inputs.get(name))
    for name in SELLER_VARIABLES + ['So_Hop_Dong']:
        out[name] = str(system.get(name) or '')
    contract_date = system.get('Ngay_Ky')
    if contract_date:
        out['Ngay_Ky'] = str(contract_date.day)
        out['Thang_Ky'] = str(contract_date.month)
        out['Nam_Ky'] = str(contract_date.year)

    subtotals = []
    for idx, line in enumerate(lines or [], start=1):
        subtotal = line_subtotal(line.get('So_Luong'), line.get('Don_Gia'))
        out['Ten_Hang_%d' % idx] = line.get('Ten_Hang') or ''
        out['DVT_%d' % idx] = line.get('DVT') or ''
        out['So_Luong_%d' % idx] = format_number(line.get('So_Luong'))
        out['Don_Gia_%d' % idx] = format_money(line.get('Don_Gia'))
        out['Thanh_Tien_%d' % idx] = format_money(subtotal)
        subtotals.append(subtotal)

    totals = compute_totals(subtotals, vat_rate)
    out['Tong_Tien_Hang'] = format_money(totals['untaxed'])
    out['Thue_Suat_VAT'] = format_number(vat_rate or 0)
    out['Tien_Thue_VAT'] = format_money(totals['vat'])
    out['Tong_Gia_Tri_HD'] = format_money(totals['total'])
    out['Tong_Gia_Tri_Bang_Chu'] = totals['words']
    return out


_TYPE_KEYS = {key for key, _label in VARIABLE_TYPES}
_SECTION_KEYS = {key for key, _label in SECTIONS}


def clean_variable_def(definition):
    """Giữ đúng các khoá người dùng được sửa (label, var_type, section, default_value), bỏ
    kiểu/nhóm không hợp lệ và nhãn rỗng. None -> {}."""
    if not definition:
        return {}
    vals = {}
    if (definition.get('label') or '').strip():
        vals['label'] = definition['label'].strip()
    if definition.get('var_type') in _TYPE_KEYS:
        vals['var_type'] = definition['var_type']
    if definition.get('section') in _SECTION_KEYS:
        vals['section'] = definition['section']
    if 'default_value' in definition:
        vals['default_value'] = (definition.get('default_value') or '').strip()
    return vals


def merge_variable_defs(field_names, existing, edits=None):
    """Bộ biến nhập mới sau khi nội dung (mẫu hoặc hợp đồng) đổi.

    field_names: tên trường có trong nội dung, theo thứ tự xuất hiện.
    existing: list dict biến đang có (giữ cấu hình nhãn/kiểu/nhóm/mặc định).
    edits: list dict người dùng vừa sửa — áp vào biến cùng tên; thứ tự trong edits là thứ tự
    ô nhập. None -> giữ thứ tự cũ, biến mới đứng sau theo thứ tự xuất hiện.
    Trả list dict {name, label, var_type, section, default_value, sequence}; biến tự điền bị bỏ,
    biến không còn trong nội dung bị bỏ, biến mới lấy nhãn/kiểu từ thư viện."""
    inputs = [n for n in field_names if not is_system_variable(n)]
    current = {d['name']: d for d in existing or []}
    edits_by_name = {d.get('name'): d for d in (edits or []) if d.get('name')}
    if edits is None:
        old_order = [d['name'] for d in existing or []]
        rank = lambda n: (old_order.index(n) if n in old_order else len(old_order), inputs.index(n))
    else:
        edit_order = [d.get('name') for d in edits]
        rank = lambda n: (edit_order.index(n) if n in edit_order else len(edit_order), inputs.index(n))
    merged = []
    for index, name in enumerate(sorted(inputs, key=rank)):
        base = current.get(name) or default_variable_def(name)
        item = {
            'name': name,
            'label': base.get('label') or name,
            'var_type': base.get('var_type') or 'text',
            'section': base.get('section') or 'other',
            'default_value': base.get('default_value') or '',
        }
        item.update(clean_variable_def(edits_by_name.get(name)))
        item['sequence'] = (index + 1) * 10
        merged.append(item)
    return merged
