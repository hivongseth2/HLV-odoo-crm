# -*- coding: utf-8 -*-
"""
check_pick_slip_stock_mismatch.py
==================================
KBC/PICK/12106: dòng lấy hàng ghi 48 Chai RP7-350G từ KBC/Tồn kho/PALLET RP7 WD40 trong khi vị
trí đó chỉ có 13 Chai (quant reserved_quantity = 0), nhưng phiếu vẫn 'Sẵn sàng'. Nghĩa là
state='assigned' KHÔNG đủ để kết luận phiếu in ra là in đúng.

Script này làm 2 việc:
  1. Soi đúng phiếu 12106: từng dòng lấy hàng vs tồn thật tại đúng vị trí, rồi in kết quả
     stock_picking._pick_slip_stock_mismatch() để xác nhận hàm chặn mới BẮT ĐƯỢC ca này.
  2. Quét toàn bộ phiếu PICK đang 'Sẵn sàng' xem còn bao nhiêu phiếu bị lệch kiểu đó — để biết
     đây là ca lẻ hay lỗi dữ liệu hệ thống, và biết cron auto-print sẽ chặn lại bao nhiêu phiếu.

CHỈ ĐỌC — không write/create/unlink gì.

Chạy bằng lệnh (trên Odoo.sh shell, sau khi đã deploy code có _pick_slip_stock_mismatch):
    python odoo-bin shell -d <TEN_DATABASE> --no-http < bin/check_pick_slip_stock_mismatch.py
"""

PICKING_NAME = "KBC/PICK/12106"  # đổi nếu cần

SEP = "=" * 100


def section(t):
    print(f"\n{SEP}\n  {t}\n{SEP}")


Picking = env['stock.picking'].sudo()  # noqa: F821
Quant = env['stock.quant'].sudo()  # noqa: F821

section(f"1) {PICKING_NAME} — từng dòng lấy hàng vs tồn thật")
pick = Picking.search([('name', '=', PICKING_NAME)], limit=1)
if not pick:
    print(f"  Không tìm thấy phiếu {PICKING_NAME!r}")
else:
    print(f"  state={pick.state!r} x_printed={pick.x_printed} "
          f"x_auto_print_requested={pick.x_auto_print_requested}")
    for line in pick.move_line_ids:
        quants = Quant.search([
            ('location_id', 'child_of', line.location_id.id),
            ('product_id', '=', line.product_id.id),
            ('lot_id', '=', line.lot_id.id or False),
            ('package_id', '=', line.package_id.id or False),
            ('owner_id', '=', line.owner_id.id or False),
        ])
        on_hand = sum(quants.mapped('quantity'))
        reserved = sum(quants.mapped('reserved_quantity'))
        flag = 'LỆCH' if line.quantity_product_uom > on_hand else 'ok'
        print(f"    [{flag:5s}] {line.product_id.default_code or line.product_id.name:18s} "
              f"phiếu ghi lấy={line.quantity_product_uom:8.2f} "
              f"tồn thật={on_hand:8.2f} đang giữ={reserved:8.2f} "
              f"tại {line.location_id.complete_name}")

    section("2) Kết quả hàm chặn _pick_slip_stock_mismatch()")
    mismatch = pick._pick_slip_stock_mismatch()
    if mismatch:
        print(f"  CHẶN (đúng như mong đợi): {mismatch}")
    else:
        print("  KHÔNG chặn — nếu phiếu này vẫn đang lệch thì hàm chặn CHƯA bắt được, phải xem lại"
              " (có thể tồn đã được sửa lại đúng sau đó, kiểm lại phần 1 trước khi kết luận).")

section("3) Quét mọi phiếu PICK đang 'Sẵn sàng' — lỗi này lẻ hay hệ thống?")
all_picks = Picking.search([
    ('state', '=', 'assigned'),
    ('picking_type_id.sequence_code', 'ilike', 'PICK'),
    ('return_id', '=', False),
], order='id')
print(f"  Tổng phiếu soát: {len(all_picks)}")
bad = []
for p in all_picks:
    try:
        msg = p._pick_slip_stock_mismatch()
    except Exception as e:
        print(f"    LỖI khi soát {p.name}: {e}")
        continue
    if msg:
        bad.append((p, msg))
print(f"  Phiếu LỆCH (cron auto-print sẽ chặn, không đưa vào hàng chờ): {len(bad)}")
for p, msg in bad[:30]:
    wh = p.picking_type_id.warehouse_id
    print(f"    {p.name:22s} kho={(wh.name or '')[:14]:14s} x_printed={str(p.x_printed):5s} {msg[:110]}")
if len(bad) > 30:
    print(f"    ... và {len(bad) - 30} phiếu nữa")

section("KẾT LUẬN")
print("  - Phần 3 ra vài phiếu -> ca lẻ do thao tác, chặn lại là đủ.")
print("  - Phần 3 ra rất nhiều phiếu -> lỗi dữ liệu hệ thống (tồn/reservation sai diện rộng), lúc")
print("    đó phải truy nguồn gây lệch chứ không chỉ chặn in; những phiếu x_printed=True trong")
print("    danh sách là phiếu ĐÃ in ra giấy với số sai, kho có thể đã đi lấy hàng không có thật.")
