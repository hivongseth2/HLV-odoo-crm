#!/usr/bin/env python3
"""
detect_barcode_location_bug.py

Quét tất cả phiếu PICK/PACK done trong N ngày gần nhất.
Phát hiện lỗi JS barcode ghi sai location vào move.line:
  - Dấu hiệu 1: move.line.location_id KHÔNG phải con của picking.location_id
                → JS đã override source location sai (tự transfer hoặc sai kệ)
  - Dấu hiệu 2: move.line.location_id == move.line.location_dest_id
                → FROM = TO = tự chuyển cho mình (net quant = 0)
  - Dấu hiệu 3: move.line.location_id là dest của 1 picking khác (stale packing zone)

Chạy: exec(open('detect_barcode_location_bug.py').read())
"""

from datetime import datetime, timedelta

DAYS_BACK        = 7       # quét N ngày gần nhất
PICKING_TYPES    = ['PICK', 'PACK']  # loại phiếu cần quét
WAREHOUSE_CODES  = []      # để trống = tất cả kho, hoặc ['TSN', 'KBC']
SHOW_OK          = False   # True = in cả phiếu không có lỗi

# ─────────────────────────────────────────────────────────────────────────────

def parent_path_contains(child_loc, parent_loc_id):
    """Kiểm tra child_loc có thuộc parent_loc_id không."""
    pp = getattr(child_loc, 'parent_path', None)
    if pp:
        return f'/{parent_loc_id}/' in pp
    # fallback: so sánh id trực tiếp
    loc = child_loc
    while loc:
        if loc.id == parent_loc_id:
            return True
        if loc.id == loc.location_id.id:
            break
        loc = loc.location_id
    return False

since = datetime.now() - timedelta(days=DAYS_BACK)

print("=" * 100)
print(f"BARCODE LOCATION BUG DETECTOR  |  {DAYS_BACK} ngay gan nhat  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 100)

# Xây domain tìm kiếm
domain = [
    ('state', '=', 'done'),
    ('date_done', '>=', since),
    ('picking_type_id.sequence_code', 'in', PICKING_TYPES),
]
if WAREHOUSE_CODES:
    domain.append(('picking_type_id.warehouse_id.code', 'in', WAREHOUSE_CODES))

pickings = env['stock.picking'].search(domain, order='date_done desc', limit=500)
print(f"\n>> Tim thay {len(pickings)} phieu done trong {DAYS_BACK} ngay gan nhat")

bug_count   = 0
ok_count    = 0
bug_pickings = []

for p in pickings:
    expected_src_id = p.location_id.id  # picking header: nguồn kỳ vọng
    bugs_in_pick = []

    for ml in p.move_line_ids:
        actual_src = ml.location_id
        actual_dst = ml.location_dest_id

        anomaly = None

        # Dấu hiệu 2 (nặng hơn): FROM = TO → self-transfer
        if actual_src.id == actual_dst.id:
            anomaly = f'SELF-TRANSFER: line location_id == location_dest_id ({actual_src.complete_name})'

        # Dấu hiệu 1: source line không thuộc picking header source
        elif not parent_path_contains(actual_src, expected_src_id):
            anomaly = (
                f'WRONG SRC: line.location={actual_src.complete_name}'
                f'  !=  picking.location={p.location_id.complete_name}'
            )

        if anomaly:
            bugs_in_pick.append({
                'ml_id'  : ml.id,
                'product': f'[{ml.product_id.default_code}] {ml.product_id.display_name[:50]}',
                'qty_done': float(getattr(ml, 'quantity', getattr(ml, 'qty_done', 0.0))),
                'anomaly': anomaly,
                'src'    : actual_src.complete_name,
                'dst'    : actual_dst.complete_name,
            })

    so_name = ''
    if p.sale_id:
        so_name = f'  SO={p.sale_id.name}'
    elif p.origin:
        so_name = f'  origin={p.origin[:20]}'

    if bugs_in_pick:
        bug_count += len(bugs_in_pick)
        bug_pickings.append(p.name)
        print(f"\n*** BUG  {p.name}  [{p.picking_type_id.sequence_code}]  "
              f"done={p.date_done}{so_name}")
        print(f"  Header: {p.location_id.complete_name}  ->  {p.location_dest_id.complete_name}")
        for b in bugs_in_pick:
            print(f"  [line {b['ml_id']}] {b['product']}")
            print(f"    qty_done={b['qty_done']:.2f}")
            print(f"    {b['anomaly']}")
            print(f"    Thuc te: {b['src']}  ->  {b['dst']}")
    else:
        ok_count += 1
        if SHOW_OK:
            print(f"  OK   {p.name}  [{p.picking_type_id.sequence_code}]  done={p.date_done}{so_name}")

print(f"\n{'='*100}")
print(f"TONG KET:")
print(f"  Tong phieu quet : {len(pickings)}")
print(f"  Phieu co loi    : {len(bug_pickings)}  ({len(bug_pickings)*100//max(len(pickings),1)}%)")
print(f"  Tong move lines loi: {bug_count}")
print(f"  Phieu OK        : {ok_count}")
if bug_pickings:
    print(f"\n  Danh sach phieu bi loi:")
    for name in bug_pickings:
        print(f"    {name}")
print(f"{'='*100}")
