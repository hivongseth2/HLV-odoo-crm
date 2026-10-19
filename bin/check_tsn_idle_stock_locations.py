# -*- coding: utf-8 -*-
"""
check_tsn_idle_stock_locations.py
=================================
Những VỊ TRÍ của kho Tân Sơn Nhì đang CÓ HÀNG nhưng KHÔNG có dịch chuyển nào (nhập, xuất,
chuyển nội bộ, điều chỉnh tồn) kể từ SINCE đến giờ — hàng nằm im, nên kiểm kê / dồn kệ.

"Dịch chuyển" tính theo stock.move.line đã hoàn tất (state = done), vị trí là nguồn HOẶC đích.
Xét ở mức move line chứ không phải stock.move vì move hay ghi vị trí cha (TSN/Stock), còn kệ
cụ thể chỉ nằm ở move line. Điều chỉnh tồn (kiểm kê) cũng sinh move line nên được tính là có
dịch chuyển.

Mỗi vị trí in: số mã, tổng SL đang tồn, lần dịch chuyển gần nhất (mọi thời điểm, '—' nếu chưa
từng có). DETAIL = True in thêm từng mã hàng trong vị trí.

CHỈ ĐỌC — không write/create/unlink gì.

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    cd ~/src/user
    odoo-bin shell -d <TEN_DATABASE> < bin/check_tsn_idle_stock_locations.py
"""

from collections import defaultdict
from datetime import datetime

WAREHOUSE_CODE = 'TSNSR'
SINCE = datetime(2026, 8, 1)
DETAIL = False
# Vị trí cần giải thích vì sao có / không có trong danh sách (in mọi move line từ SINCE).
WATCH = ['TSN/Stock/G1/D4-T2/THUNG2']
QTY_EPS = 0.001
SEP = "=" * 100

Quant = env['stock.quant'].sudo()
MoveLine = env['stock.move.line'].sudo()

warehouse = env['stock.warehouse'].sudo().search([('code', '=', WAREHOUSE_CODE)], limit=1)
if not warehouse:
    raise SystemExit(f"Không thấy kho mã {WAREHOUSE_CODE}")

locations = env['stock.location'].sudo().search([
    ('id', 'child_of', warehouse.view_location_id.id), ('usage', '=', 'internal'),
])
print(f"\n{SEP}\n  {warehouse.name} ({warehouse.code}): vị trí có hàng nhưng không dịch chuyển từ "
      f"{SINCE:%d/%m/%Y}\n{SEP}")
print(f"  Vị trí nội bộ của kho: {len(locations)}")

# Chỉ quant dương: quant âm là tồn ảo do xuất quá, không phải hàng đang nằm trên kệ.
quants = Quant.search([('location_id', 'in', locations.ids), ('quantity', '>', QTY_EPS)])
stock = defaultdict(lambda: Quant.browse())
for quant in quants:
    stock[quant.location_id] |= quant
print(f"  Vị trí đang có hàng: {len(stock)}")


def last_move_dates(location_ids, domain_extra=()):
    """{location_id: ngày move line done gần nhất}, tính cả chiều nguồn lẫn đích."""
    last = {}
    for field in ('location_id', 'location_dest_id'):
        domain = [(field, 'in', location_ids), ('state', '=', 'done'), *domain_extra]
        for loc, date in MoveLine._read_group(domain, [field], ['date:max']):
            if date and (loc.id not in last or date > last[loc.id]):
                last[loc.id] = date
    return last


stocked_ids = [loc.id for loc in stock]
moved_since = last_move_dates(stocked_ids, [('date', '>=', SINCE)])
idle = sorted((loc for loc in stock if loc.id not in moved_since), key=lambda l: l.complete_name)
last_ever = last_move_dates([loc.id for loc in idle])

for loc in idle:
    loc_quants = stock[loc]
    last = last_ever.get(loc.id)
    print(f"\n  {loc.complete_name} — {len(loc_quants.product_id)} mã, tổng SL "
          f"{sum(loc_quants.mapped('quantity')):g} | dịch chuyển cuối: {f'{last:%d/%m/%Y}' if last else '—'}")
    if DETAIL:
        for quant in loc_quants.sorted(lambda q: q.product_id.default_code or ''):
            lot = f" lô {quant.lot_id.name}" if quant.lot_id else ''
            print(f"      [{quant.product_id.default_code or '—'}] {quant.product_id.name[:50]}{lot}: "
                  f"{quant.quantity:g}")

print(f"\n{SEP}")
print(f"  Vị trí có hàng nằm im từ {SINCE:%d/%m/%Y}: {len(idle)}/{len(stock)}")
print(SEP)


def explain_location(name):
    """In vì sao 1 vị trí có / không nằm trong danh sách nằm im: tồn hiện tại + move line từ SINCE."""
    loc = locations.filtered(lambda l: l.complete_name == name)
    print(f"\n  VÌ SAO: {name}")
    if not loc:
        print("      không thuộc kho này (hoặc không phải vị trí nội bộ)")
        return
    print(f"      có hàng: {'có' if loc in stock else 'KHÔNG (không có quant dương)'}"
          f" | nằm im: {'có' if loc in idle else 'KHÔNG'}")
    for quant in stock.get(loc, Quant.browse()):
        print(f"      tồn [{quant.product_id.default_code or '—'}] {quant.quantity:g}")
    lines = MoveLine.search([
        '|', ('location_id', '=', loc.id), ('location_dest_id', '=', loc.id),
        ('state', '=', 'done'), ('date', '>=', SINCE),
    ], order='date')
    if not lines:
        print(f"      không có move line done nào từ {SINCE:%d/%m/%Y}")
    for line in lines:
        print(f"      {line.date:%d/%m/%Y %H:%M} {line.reference or '—'} [{line.product_id.default_code or '—'}] "
              f"{line.location_id.complete_name} → {line.location_dest_id.complete_name} SL {line.quantity:g}")


for name in WATCH:
    explain_location(name)
