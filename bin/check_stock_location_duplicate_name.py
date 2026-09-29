# -*- coding: utf-8 -*-
"""
check_stock_location_duplicate_name.py
======================================
Rà soát các VỊ TRÍ KHO (stock.location) đang hoạt động có TÊN ĐẦY ĐỦ
(complete_name, vd "KBC/Stock/Kệ A1") trùng nhau. Vị trí đã lưu trữ
(active = False) KHÔNG tính.

Trùng tên đầy đủ làm nhập/xuất theo tên vị trí (import Excel, quét mã, MISA
đồng bộ) chọn nhầm vị trí và hàng bị chia ra hai nơi mà nhìn tên không phân biệt.

Hai mức:
  1. TRÙNG HẲN — complete_name giống từng ký tự.
  2. GẦN TRÙNG — chỉ khác hoa/thường hoặc khoảng trắng (vd "Kệ A1" vs "kệ  a1 ").
     Mức này hay gặp hơn vì người nhập gõ thừa dấu cách, và vẫn gây nhầm như trên.

Mỗi vị trí in kèm công ty, loại (usage), số quant và tổng tồn để biết nên giữ
cái nào, lưu trữ/gộp cái nào.

CHỈ ĐỌC — không write/create/unlink gì.

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_stock_location_duplicate_name.py
"""

import re
from collections import defaultdict

# True: chỉ coi là trùng khi CÙNG công ty (hai công ty dùng chung tên vị trí là
# bình thường). False: gom cả khác công ty.
SAME_COMPANY_ONLY = False

SEP = "=" * 90
print(f"\n{SEP}\n  RÀ SOÁT VỊ TRÍ KHO TRÙNG TÊN ĐẦY ĐỦ (bỏ vị trí đã lưu trữ)\n{SEP}")

Location = env['stock.location'].sudo()
locations = Location.search([('active', '=', True)], order='complete_name, id')
print(f"  Tổng vị trí đang hoạt động: {len(locations)}")

# Tồn theo vị trí, để biết vị trí nào đang chứa hàng (không nên lưu trữ bừa).
quant_stats = {
    loc.id: (count, qty or 0.0)
    for loc, qty, count in env['stock.quant'].sudo()._read_group(
        [('location_id', 'in', locations.ids)],
        ['location_id'],
        ['quantity:sum', '__count'],
    )
}


def normalize(name):
    return re.sub(r'\s+', ' ', (name or '').strip()).casefold()


def group_key(loc, name):
    return (loc.company_id.id, name) if SAME_COMPANY_ONLY else name


exact = defaultdict(list)
fuzzy = defaultdict(list)
for loc in locations:
    exact[group_key(loc, loc.complete_name or '')].append(loc)
    fuzzy[group_key(loc, normalize(loc.complete_name))].append(loc)

exact_groups = [locs for locs in exact.values() if len(locs) > 1]
exact_ids = {loc.id for locs in exact_groups for loc in locs}
# Nhóm gần trùng chỉ báo khi có ít nhất 2 cách viết khác nhau — nếu mọi vị trí
# trong nhóm viết y hệt thì đã nằm ở mục trùng hẳn rồi.
fuzzy_groups = [
    locs for locs in fuzzy.values()
    if len(locs) > 1 and len({loc.complete_name for loc in locs}) > 1
]


def print_location(loc):
    count, qty = quant_stats.get(loc.id, (0, 0.0))
    warehouse = loc.warehouse_id.name or '-'
    print(
        f"      #{loc.id:<6} {loc.complete_name!r}\n"
        f"              công ty={loc.company_id.name or '(dùng chung)'!r} kho={warehouse!r} "
        f"usage={loc.usage} barcode={loc.barcode or '-'!r} "
        f"quant={count} tổng tồn={qty:g}"
    )


print(f"\n{SEP}\n  1) TRÙNG HẲN: {len(exact_groups)} nhóm\n{SEP}")
for locs in exact_groups:
    print(f"\n  {locs[0].complete_name!r} — {len(locs)} vị trí:")
    for loc in locs:
        print_location(loc)

print(f"\n{SEP}\n  2) GẦN TRÙNG (khác hoa/thường, khoảng trắng): {len(fuzzy_groups)} nhóm\n{SEP}")
for locs in fuzzy_groups:
    print(f"\n  ~ {normalize(locs[0].complete_name)!r} — {len(locs)} vị trí:")
    for loc in locs:
        print_location(loc)

print(f"\n{SEP}")
if not exact_groups and not fuzzy_groups:
    print("  => KHÔNG có vị trí đang hoạt động nào trùng tên đầy đủ.")
else:
    print(
        f"  => {len(exact_groups)} nhóm trùng hẳn ({len(exact_ids)} vị trí), "
        f"{len(fuzzy_groups)} nhóm gần trùng.\n"
        "  Cách xử lý (làm thủ công, script này KHÔNG tự sửa):\n"
        "    - Giữ vị trí đang có tồn / đang được loại phiếu, quy tắc tồn kho trỏ tới.\n"
        "    - Vị trí thừa còn tồn: chuyển hết hàng sang vị trí giữ lại trước, rồi mới lưu trữ.\n"
        "    - Vị trí thừa không tồn: lưu trữ hoặc đổi tên cho khác đi."
    )
print(SEP)
