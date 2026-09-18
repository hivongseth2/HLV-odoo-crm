# -*- coding: utf-8 -*-
"""
check_partner_dedup_structure.py
================================
Đo CẤU TRÚC THẬT của mã khách trên phiếu giao, để trả lời đúng một câu hỏi:

    Gom theo `commercial_partner_id` (pháp nhân gốc) có gom được như gom theo TÊN không?

Vì sao phải đo: con số "351 mã = 176 khách thật" trong plan/dieu-phoi-ben-cam được tính
bằng cách gom theo **TÊN khách**. Nhưng `hlv_vtracking` lại gom bằng **commercial_partner_id**.
Hai cách này CHỈ cho cùng kết quả khi các mã trùng tên là liên hệ con của cùng một công ty.
Nếu chúng là các công ty độc lập (mỗi mã tự là pháp nhân gốc của chính nó) thì
commercial_partner_id gom được ĐÚNG SỐ KHÔNG, và code đang dựa trên một giả định sai.

Chạy bằng lệnh:
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_partner_dedup_structure.py

Script này CHỈ ĐỌC, không ghi gì, không sửa gì.
"""

DATE_FROM = '2026-06-01'   # <-- đổi nếu muốn khoảng khác
DATE_TO = '2026-12-31'
TOP_N = 25                 # số nhóm tên in chi tiết

SEP = '=' * 78


def section(title):
    print('\n%s\n  %s\n%s' % (SEP, title, SEP))


try:
    from odoo.addons.hlv_geo_utils.tools.geo_text import normalize_name
except ImportError:                                    # module chưa cài -> tự chuẩn hoá thô
    import re
    import unicodedata

    def normalize_name(value):
        text = unicodedata.normalize('NFD', str(value or '')).lower()
        text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
        return re.sub(r'[^a-z0-9]', '', text.replace('đ', 'd'))


# ─────────────────────────────────────────────────────────────────────
# A. Tập mã khách xuất hiện trên phiếu GIAO trong khoảng ngày
# ─────────────────────────────────────────────────────────────────────
section('A. PHẠM VI ĐO')

Picking = env['stock.picking'].sudo()
domain = [
    ('picking_type_id.code', '=', 'outgoing'),
    ('scheduled_date', '>=', DATE_FROM),
    ('scheduled_date', '<=', DATE_TO),
    ('state', 'not in', ('cancel', 'draft')),
]
pickings = Picking.search(domain)
partners = pickings.mapped('partner_id')

print('Khoảng ngày            : %s → %s' % (DATE_FROM, DATE_TO))
print('Số phiếu giao (outgoing): %s' % len(pickings))
print('Số MÃ khách khác nhau   : %s   <-- so với con số 351 trong plan' % len(partners))
print('Tổng res.partner trong DB: %s' % env['res.partner'].sudo().search_count([]))

# Bản gốc của con số 351 đo trên phiếu ĐÃ GIAO XONG (date_done). In thêm để so cho đúng
# cùng một phạm vi, tránh cãi nhau vì hai bên đếm hai tập khác nhau.
done = Picking.search([
    ('picking_type_id.code', '=', 'outgoing'), ('state', '=', 'done'),
    ('date_done', '>=', DATE_FROM), ('date_done', '<=', DATE_TO),
])
print('Chỉ phiếu ĐÃ GIAO XONG    : %s phiếu, %s mã khách'
      % (len(done), len(done.mapped('partner_id'))))

# ─────────────────────────────────────────────────────────────────────
# B. Ba cách gom, ba con số
# ─────────────────────────────────────────────────────────────────────
section('B. GOM THEO BA CÁCH — ĐÂY LÀ CÂU TRẢ LỜI CHÍNH')

by_commercial = {}
by_name = {}
for partner in partners:
    by_commercial.setdefault(partner.commercial_partner_id.id, []).append(partner)
    by_name.setdefault(normalize_name(partner.name), []).append(partner)

print('1. Không gom (partner_id)          : %s' % len(partners))
print('2. Gom theo commercial_partner_id  : %s   <-- cách hlv_vtracking đang dùng'
      % len(by_commercial))
print('3. Gom theo TÊN đã chuẩn hoá       : %s   <-- cách ra con số 176 trong plan'
      % len(by_name))
print('')
gap = len(by_commercial) - len(by_name)
if gap <= 0:
    print('=> commercial_partner_id gom BẰNG HOẶC TỐT HƠN gom theo tên. Giả định của code ĐÚNG.')
else:
    print('=> commercial_partner_id BỎ SÓT %s nhóm so với gom theo tên.' % gap)
    print('   Nghĩa là có những mã trùng tên nhưng KHÔNG cùng pháp nhân gốc —')
    print('   `_compute_place_id` sẽ không tìm thấy điểm giao cho các mã đó.')

# ─────────────────────────────────────────────────────────────────────
# C. Cấu trúc: mã là công ty độc lập hay liên hệ con?
# ─────────────────────────────────────────────────────────────────────
section('C. CẤU TRÚC TỪNG MÃ')

own_root = [p for p in partners if p.commercial_partner_id.id == p.id]
child = [p for p in partners if p.parent_id]
company_flag = [p for p in partners if p.is_company]
print('Mã tự là pháp nhân gốc của chính nó : %s' % len(own_root))
print('Mã có parent_id (liên hệ con)       : %s' % len(child))
print('Mã có is_company = True             : %s' % len(company_flag))
print('')
print('Nếu "mã tự là pháp nhân gốc" gần bằng tổng số mã thì commercial_partner_id')
print('KHÔNG gom được gì — mỗi mã là một công ty riêng trong mắt Odoo.')

# ─────────────────────────────────────────────────────────────────────
# D. Các tên có nhiều mã — và commercial_partner_id có gom được không
# ─────────────────────────────────────────────────────────────────────
section('D. TOP %s TÊN CÓ NHIỀU MÃ NHẤT' % TOP_N)

multi = sorted(
    ((key, plist) for key, plist in by_name.items() if len(plist) > 1),
    key=lambda item: -len(item[1]),
)
print('Số tên có từ 2 mã trở lên: %s' % len(multi))
print('')
for _key, plist in multi[:TOP_N]:
    roots = {p.commercial_partner_id.id for p in plist}
    verdict = 'GOM ĐƯỢC' if len(roots) == 1 else 'KHÔNG GOM ĐƯỢC (%s pháp nhân gốc)' % len(roots)
    print('%-38s %2s mã  ->  %s' % ((plist[0].name or '')[:38], len(plist), verdict))
    for p in plist:
        print('      id=%-7s ref=%-14s is_company=%-5s parent=%-28s root=%s' % (
            p.id, (p.ref or '-')[:14], p.is_company,
            (p.parent_id.name or '-')[:28], p.commercial_partner_id.id,
        ))
    print('')

# ─────────────────────────────────────────────────────────────────────
# E. Ảnh hưởng thật lên hlv_vtracking
# ─────────────────────────────────────────────────────────────────────
section('E. ẢNH HƯỞNG LÊN ĐIỂM GIAO CỦA hlv_vtracking')

Place = env['hlv.vtracking.place'].sudo()
places = Place.search([('partner_id', '!=', False)])
print('Số điểm giao đã gắn đối tác: %s' % len(places))

place_roots = {place.partner_id.commercial_partner_id.id for place in places}
hit = [p for p in partners if p.commercial_partner_id.id in place_roots]
print('Mã khách tra ra được điểm giao qua commercial_partner_id: %s/%s'
      % (len(hit), len(partners)))

place_names = {normalize_name(place.partner_id.name) for place in places}
hit_name = [p for p in partners if normalize_name(p.name) in place_names]
print('Mã khách tra ra được nếu gom theo TÊN                    : %s/%s'
      % (len(hit_name), len(partners)))
print('')
extra = len(hit_name) - len(hit)
if extra > 0:
    print('=> Gom theo tên tìm thêm được %s mã. Đó là %s chứng từ sẽ KHÔNG có thói quen'
          % (extra, extra))
    print('   khách và KHÔNG có cụm dự phòng nếu vẫn dùng commercial_partner_id.')
    print('')
    print('   Mười mã bị bỏ sót đầu tiên:')
    missed = [p for p in hit_name if p.commercial_partner_id.id not in place_roots]
    for p in missed[:10]:
        print('     id=%-7s ref=%-14s %s' % (p.id, (p.ref or '-')[:14], (p.name or '')[:44]))
else:
    print('=> Không mã nào bị bỏ sót. commercial_partner_id là đủ.')

print('\n%s\n  HẾT\n%s' % (SEP, SEP))
