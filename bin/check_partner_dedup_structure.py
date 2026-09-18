# -*- coding: utf-8 -*-
"""
check_partner_dedup_structure.py   (bản 2 — sửa sai của bản 1)
==============================================================
BẢN 1 (`check_partner_dedup_structure_v1.py`) ĐO SAI. Nó gom theo TÊN CỦA LIÊN HỆ rồi kết
luận "commercial_partner_id bỏ sót 93 nhóm". Kết luận đó sai vì tập đem ra so là rác:

  * "****"        166 mã, 165 pháp nhân gốc khác nhau — liên hệ sàn TMĐT bị che tên.
  * "Ms Hoa"      4 mã nằm ở LOTTE CHEMICAL / PHỒN THỊNH / ACC — ba công ty khác hẳn nhau.
  * "anh Trường"  3 mã ở 3 công ty khác nhau.

Gom theo tên liên hệ thì nhập cả những thứ đó làm một. Nên "93 nhóm bỏ sót" KHÔNG chứng
minh được commercial_partner_id sai — nó chỉ chứng minh gom theo tên liên hệ là nguy hiểm.

Điều bản 1 chỉ ra ĐÚNG, nhưng vì một lý do khác hẳn: cùng một công ty thật đang có **nhiều
bản ghi CÔNG TY** trong Odoo. TOPBAND có 684 và 16461; SUMMIT POLYMERS có 132 và 981; HORY
có 803 và 2434; DONGJIN có 18188 và 133. Điểm giao gắn vào bản ghi này thì đơn đi qua bản
ghi kia không tra ra gì.

Bản 2 đo đúng giả thuyết đó:

  1. Gom theo TÊN CỦA PHÁP NHÂN GỐC (không phải tên liên hệ) — "Ms Hoa" quy về LOTTE
     CHEMICAL nên không còn nhập nhầm.
  2. Gom theo MÃ SỐ THUẾ (`vat`) — bằng chứng chắc nhất rằng hai bản ghi là một công ty.
  3. Mô phỏng `_compute_place_id` theo 3 cách, và **kiểm tra ngược** xem cách mới có ghép
     nhầm sang công ty khác không.

Chạy bằng lệnh:
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_partner_dedup_structure.py

Script này CHỈ ĐỌC, không ghi gì, không sửa gì.
"""

DATE_FROM = '2026-06-01'
DATE_TO = '2026-12-31'
TOP_N = 30

SEP = '=' * 78


def section(title):
    print('\n%s\n  %s\n%s' % (SEP, title, SEP))


try:
    from odoo.addons.hlv_geo_utils.tools.geo_text import normalize_name
except ImportError:
    import re
    import unicodedata

    def normalize_name(value):
        text = unicodedata.normalize('NFD', str(value or '')).lower()
        text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
        return re.sub(r'[^a-z0-9]', '', text.replace('đ', 'd'))


def norm_vat(value):
    """Mã số thuế chỉ giữ chữ và số, chữ thường. Rỗng/None -> ''."""
    return ''.join(c for c in str(value or '') if c.isalnum()).lower()


# ─────────────────────────────────────────────────────────────────────
section('A. PHẠM VI — VÀ SUBSET NÀO ỨNG VỚI CON SỐ 351 TRONG PLAN')
# ─────────────────────────────────────────────────────────────────────
Picking = env['stock.picking'].sudo()
pickings = Picking.search([
    ('picking_type_id.code', '=', 'outgoing'),
    ('scheduled_date', '>=', DATE_FROM),
    ('scheduled_date', '<=', DATE_TO),
    ('state', 'not in', ('cancel', 'draft')),
])
partners = pickings.mapped('partner_id')
print('Tất cả phiếu OUT: %s phiếu, %s mã khách' % (len(pickings), len(partners)))
print('')
print('Tách theo KHO. Con số 351 trong plan đo trên chuyến xe công ty chạy từ Bến Cam,')
print('KHÔNG phải trên toàn bộ phiếu OUT — phần lớn 3282 mã kia là đơn web/sàn, không bao')
print('giờ lên xe công ty. Nhìn bảng dưới để biết subset nào mới là phần điều phối lo:')
print('')
print('  %-40s %8s %9s' % ('Kho / loại phiếu', 'phiếu', 'mã khách'))
groups = {}
for picking in pickings:
    key = '%s / %s' % (
        picking.picking_type_id.warehouse_id.name or '-', picking.picking_type_id.name or '-',
    )
    groups.setdefault(key, [set(), set()])
    groups[key][0].add(picking.id)
    groups[key][1].add(picking.partner_id.id)
for key, (pids, parts) in sorted(groups.items(), key=lambda item: -len(item[1][0])):
    print('  %-40s %8s %9s' % (key[:40], len(pids), len(parts)))

# ─────────────────────────────────────────────────────────────────────
section('B. GOM THEO PHÁP NHÂN GỐC, TÊN PHÁP NHÂN GỐC, VÀ MÃ SỐ THUẾ')
# ─────────────────────────────────────────────────────────────────────
roots = partners.mapped('commercial_partner_id')
by_root_name = {}
by_vat = {}
for root in roots:
    by_root_name.setdefault(normalize_name(root.name), set()).add(root.id)
    key = norm_vat(root.vat)
    if key:
        by_vat.setdefault(key, set()).add(root.id)

dup_name = {k: v for k, v in by_root_name.items() if len(v) > 1 and k}
dup_vat = {k: v for k, v in by_vat.items() if len(v) > 1}
with_vat = [r for r in roots if norm_vat(r.vat)]

print('Mã khách trên phiếu                   : %s' % len(partners))
print('Pháp nhân gốc khác nhau               : %s   <-- hlv_vtracking đang gom tới đây'
      % len(roots))
print('Nếu gom thêm theo TÊN pháp nhân gốc   : %s' % len(by_root_name))
print('')
print('Tên pháp nhân gốc TRÙNG (>1 bản ghi công ty) : %s' % len(dup_name))
print('Mã số thuế TRÙNG (>1 bản ghi công ty)         : %s' % len(dup_vat))
print('Pháp nhân gốc có khai mã số thuế             : %s/%s' % (len(with_vat), len(roots)))
print('')
print('=> Hai con số "TRÙNG" khác 0 nghĩa là: vấn đề KHÔNG phải commercial_partner_id sai,')
print('   mà là Odoo đang có NHIỀU BẢN GHI CÔNG TY cho cùng một công ty thật.')

# ─────────────────────────────────────────────────────────────────────
section('C. %s TÊN CÔNG TY CÓ NHIỀU BẢN GHI NHẤT — SOÁT TAY' % TOP_N)
# ─────────────────────────────────────────────────────────────────────
Partner = env['res.partner'].sudo()
for _key, ids in sorted(dup_name.items(), key=lambda item: -len(item[1]))[:TOP_N]:
    records = Partner.browse(sorted(ids))
    vats = {norm_vat(r.vat) for r in records if norm_vat(r.vat)}
    if len(vats) > 1:
        verdict = 'MST KHÁC NHAU -> có thể là 2 công ty thật, ĐỪNG GỘP'
    elif len(vats) == 1:
        verdict = 'CÙNG MST -> chắc chắn một công ty'
    else:
        verdict = 'không bản ghi nào khai MST -> phải nhìn địa chỉ'
    print('%s  (%s bản ghi)  %s' % ((records[0].name or '')[:44], len(records), verdict))
    for r in records:
        children = Partner.search_count([('parent_id', '=', r.id)])
        print('    id=%-7s ref=%-16s vat=%-15s con=%-4s %s' % (
            r.id, (r.ref or '-')[:16], (r.vat or '-')[:15], children, (r.street or '-')[:36],
        ))
    print('')

# ─────────────────────────────────────────────────────────────────────
section('D. MÔ PHỎNG _compute_place_id — BA CÁCH GHÉP')
# ─────────────────────────────────────────────────────────────────────
Place = env['hlv.vtracking.place'].sudo()
places = Place.search([('partner_id', '!=', False)])
print('Số điểm giao đã gắn đối tác: %s' % len(places))
print('')

place_roots = {p.partner_id.commercial_partner_id.id for p in places}
place_root_names = {normalize_name(p.partner_id.commercial_partner_id.name) for p in places}
place_root_names.discard('')
place_vats = {norm_vat(p.partner_id.commercial_partner_id.vat) for p in places}
place_vats.discard('')


def match_id(partner):
    return partner.commercial_partner_id.id in place_roots


def match_name(partner):
    return normalize_name(partner.commercial_partner_id.name) in place_root_names


def match_vat(partner):
    key = norm_vat(partner.commercial_partner_id.vat)
    return bool(key) and key in place_vats


by_id = [p for p in partners if match_id(p)]
by_id_name = [p for p in partners if match_id(p) or match_name(p)]
by_all = [p for p in partners if match_id(p) or match_name(p) or match_vat(p)]

print('1. Chỉ commercial_partner_id (hiện tại) : %s mã' % len(by_id))
print('2. + tên pháp nhân gốc                  : %s mã' % len(by_id_name))
print('3. + tên pháp nhân gốc + mã số thuế     : %s mã' % len(by_all))
print('')
print('Quy ra số PHIẾU được hưởng (cái này mới là thứ điều phối thấy):')
for label, group in (('hiện tại', by_id), ('+ tên gốc', by_id_name), ('+ tên + MST', by_all)):
    ids = {p.id for p in group}
    print('  %-14s %5s/%s phiếu' % (
        label, len([pk for pk in pickings if pk.partner_id.id in ids]), len(pickings),
    ))

# ─────────────────────────────────────────────────────────────────────
section('E. KIỂM TRA NGƯỢC — CÁCH 2 CÓ GHÉP NHẦM KHÔNG')
# ─────────────────────────────────────────────────────────────────────
print('Mỗi dòng: mã khách mà cách 2 tìm thêm được, và điểm giao nó sẽ ghép vào.')
print('Soát tay: dòng nào ghép sang một CÔNG TY KHÁC thì cách 2 không dùng được.')
print('')
place_by_name = {}
for place in places:
    place_by_name.setdefault(
        normalize_name(place.partner_id.commercial_partner_id.name), place,
    )
extra = [p for p in partners if match_name(p) and not match_id(p)]
print('Số mã tìm thêm: %s' % len(extra))
print('')
for p in extra[:40]:
    root = p.commercial_partner_id
    place = place_by_name.get(normalize_name(root.name))
    target = place.partner_id.commercial_partner_id if place else None
    print('  đơn đi qua root id=%-7s %s' % (root.id, (root.name or '')[:46]))
    print('      ghép vào điểm "%s" của root id=%s %s' % (
        (place.name or '')[:26] if place else '-',
        target.id if target else '-',
        (target.name or '')[:34] if target else '-',
    ))

print('\n%s\n  HẾT\n%s' % (SEP, SEP))
