# -*- coding: utf-8 -*-
"""
check_auto_print_candidates.py
===============================
Xem TRƯỚC (dry-run) cron "Tự động gửi in phiếu lấy hàng đủ hàng"
(stock_picking.cron_auto_queue_print_when_full) sẽ gửi đúng những phiếu nào, TRƯỚC KHI bật nó
trên PRD — vì hook cũ chưa từng chạy nên đang tồn đọng một lượng phiếu 'assigned' khá lớn, cần
biết chính xác bao nhiêu phiếu sẽ ra giấy ở kho nào.

Dùng ĐÚNG domain của code (_auto_print_candidate_domain) nên không có chuyện script kiểm một
kiểu, cron chạy một kiểu.

CHỈ ĐỌC — không write/create/unlink gì.

Chạy bằng lệnh (trên Odoo.sh shell):
    python odoo-bin shell -d <TEN_DATABASE> --no-http < bin/check_auto_print_candidates.py
"""

SEP = "=" * 100


def section(t):
    print(f"\n{SEP}\n  {t}\n{SEP}")


Picking = env['stock.picking'].sudo()  # noqa: F821
Queue = env['hlv.iot.print.queue'].sudo()  # noqa: F821

base_domain = [
    ('state', '=', 'assigned'),
    ('picking_type_id.sequence_code', 'ilike', 'PICK'),
    ('return_id', '=', False),
]

section("1) Vì sao 88 phiếu 'assigned' rụng dần qua từng điều kiện")
steps = [
    ("PICK đang 'assigned' (chưa lọc gì)", []),
    ("+ chưa từng tự động gửi in", [('x_auto_print_requested', '=', False)]),
    ("+ CHƯA in (x_printed = False)", [('x_printed', '=', False)]),
    ("+ đã có Hình thức giao hàng", [('x_pick_delivery_type', '!=', False)]),
    ("+ kho ĐÃ gán máy in IoT", [('picking_type_id.warehouse_id.x_iot_printer_device_id', '!=', False)]),
]
cumulative = list(base_domain)
for label, extra in steps:
    cumulative += extra
    print(f"  {label:45s} -> {Picking.search_count(cumulative):4d} phiếu")

section("2) Domain thật của code — số phiếu cron sẽ gửi ở lượt đầu")
domain = Picking._auto_print_candidate_domain()
candidates = Picking.search(domain, order='id')
print(f"  Tổng: {len(candidates)} phiếu")
by_wh = {}
for p in candidates:
    wh = p.picking_type_id.warehouse_id
    by_wh.setdefault(wh, Picking.browse())
    by_wh[wh] |= p
for wh, picks in by_wh.items():
    limit = wh.x_iot_queue_limit or 0
    active = Queue.count_active_for_warehouse(wh.id)
    print(f"\n  {wh.name} (máy in: {wh.x_iot_printer_device_id.name or '(chưa gán)'})")
    print(f"    số phiếu sẽ gửi : {len(picks)}")
    print(f"    hàng chờ        : đang {active}/{limit if limit else 'không giới hạn'}"
          f"{'  -> phần vượt giới hạn sẽ bị hoãn sang lượt cron sau, không mất' if limit else ''}")
    # Mẫu phiếu của kho: nếu trỏ sai report (VD Package Labels) thì máy kho in ra nhãn kiện chứ
    # không phải phiếu lấy hàng — kiểm trước khi bật cron, sai là in sai hàng loạt.
    print(f"    mẫu phiếu       : {wh.x_iot_report_id.name if wh.x_iot_report_id else '(mặc định: Hoạt động lấy hàng TSN)'}")
    for p in picks[:15]:
        so = p.sale_id or p.move_ids.sale_line_id.order_id[:1]
        print(f"      {p.name:22s} {so.name if so else '(không rõ đơn)':22s} "
              f"HTGH={(p.x_pick_delivery_type or '')[:18]:18s} scheduled={p.scheduled_date}")
    if len(picks) > 15:
        print(f"      ... và {len(picks) - 15} phiếu nữa")

section("3) Phiếu bị LOẠI và lý do (để chắc không loại oan)")
excluded = Picking.search(base_domain) - candidates
print(f"  Tổng bị loại: {len(excluded)}")
reasons = {}
for p in excluded:
    wh = p.picking_type_id.warehouse_id
    if p.x_printed:
        key = 'đã in rồi (x_printed)'
    elif p.x_auto_print_requested:
        key = 'đã tự động gửi in trước đó'
    elif not p.x_pick_delivery_type:
        key = 'thiếu Hình thức giao hàng (sale nhập là tự vào lượt sau)'
    elif not (wh and wh.x_iot_printer_device_id):
        key = f'kho chưa gán máy in IoT: {wh.name if wh else "(không rõ kho)"}'
    else:
        key = 'khác'
    reasons[key] = reasons.get(key, 0) + 1
for key, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
    print(f"    {count:4d}  {key}")

section("KẾT LUẬN")
print("  - Số ở phần 2 chính là lượng giấy kho sẽ nhận sau khi bật cron (giới hạn 50 phiếu/lượt,")
print("    cộng giới hạn hàng chờ của từng kho). Thấy con số này lớn quá thì cho kho in tay cho")
print("    hết phiếu tồn trước, rồi mới bật cron.")
print("  - Kiểm dòng 'mẫu phiếu' của từng kho: trỏ sai report (VD Package Labels) là in ra nhãn")
print("    kiện chứ không phải phiếu lấy hàng.")
