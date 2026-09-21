# -*- coding: utf-8 -*-
"""
check_auto_print_hook_fires.py
===============================
Setting "Tự động gửi in khi phiếu đủ hàng" (auto_print_pick_slip_when_full) ĐANG BẬT, phiếu PICK
đã "Sẵn sàng", nhưng không có gì vào hàng chờ in IoT.

check_auto_print_when_full.py trước đây chỉ kiểm các điều kiện BÊN TRONG
_auto_queue_print_when_full(), và force_auto_print_test.py chỉ chứng minh logic đó chạy được KHI
ĐƯỢC GỌI — cả hai đều KHÔNG trả lời được câu hỏi thật sự: cái hook đó có BAO GIỜ được gọi trong
vận hành thật hay không.

Giả thuyết cần xác nhận/loại trừ ở script này:
    stock.picking.state là field COMPUTE + STORE (_compute_state) trong Odoo core. Giá trị của nó
    được ORM ghi xuống DB bằng đường flush recompute (model._write), KHÔNG đi qua write() công
    khai. Hook auto-print hiện chỉ móc ở:
        - stock_picking.create()               -> lúc tạo phiếu state còn 'draft', không bao giờ khớp
        - stock_picking.write() khi vals['state'] == 'assigned'  -> reservation KHÔNG đi qua đây
    Nếu đúng, hook chưa từng chạy lần nào trong vận hành thật (chỉ chạy khi gọi tay bằng
    force_auto_print_test.py), nghĩa là KHÔNG phải lỗi "worker chạy code cũ".

Dấu hiệu XÁC NHẬN giả thuyết (đọc phần 2 và 3 bên dưới):
    - Rất nhiều phiếu PICK đang 'assigned' mà x_auto_print_requested = False, VÀ
    - Số phiếu x_auto_print_requested = True gần như bằng 0 (hoặc chỉ đúng những phiếu đã bị
      chạy tay bằng force_auto_print_test.py).
Dấu hiệu BÁC BỎ giả thuyết:
    - Có kha khá phiếu x_auto_print_requested = True rải rác theo thời gian -> hook CÓ chạy, lỗi
      nằm ở chỗ khác (xem phần 4/5: kho chưa gán máy in, hàng chờ đầy, hoặc không ai in ra giấy).

CHỈ ĐỌC — không write/create/unlink gì.

Chạy bằng lệnh (trên Odoo.sh shell):
    python odoo-bin shell -d <TEN_DATABASE> --no-http < bin/check_auto_print_hook_fires.py
"""

ORDER_NAME = "DH125524949236775"  # đổi nếu cần
WAREHOUSE_CODE = "KBC"  # kho Bến Cam — đổi nếu cần

SEP = "=" * 100


def section(t):
    print(f"\n{SEP}\n  {t}\n{SEP}")


ICP = env['ir.config_parameter'].sudo()  # noqa: F821
Picking = env['stock.picking'].sudo()  # noqa: F821
Queue = env['hlv.iot.print.queue'].sudo()  # noqa: F821

section("1) Setting")
auto_param = ICP.get_param('hlv_sale_delivery_planning.auto_print_pick_slip_when_full', default='(chưa set)')
lock_param = ICP.get_param('hlv_sale_delivery_planning.lock_pick_slip_requests', default='(chưa set)')
print(f"  auto_print_pick_slip_when_full = {auto_param!r}")
print(f"  lock_pick_slip_requests        = {lock_param!r}")
# Đúng y hệt điều kiện trong _auto_queue_print_when_full() — nếu giá trị lưu là dạng khác
# ('False'/''/'1'), phần so sánh này sẽ lộ ra ngay.
print(f"  -> điều kiện code ('1'/'True'/'true'): auto={'PASS' if str(auto_param) in ('1', 'True', 'true') else 'CHẶN'}"
      f", lock={'ĐANG KHÓA' if str(lock_param) in ('1', 'True', 'true') else 'không khóa'}")

section("2) stock.picking.state có phải compute+store không (gốc của giả thuyết)")
state_field = Picking._fields['state']
print(f"  compute = {state_field.compute!r}")
print(f"  store   = {state_field.store}")
print(f"  -> {'COMPUTE+STORE: giá trị ghi qua _write(), write() hook KHÔNG bắt được'
        if (state_field.compute and state_field.store) else
        'field thường: write() hook CÓ thể bắt được, giả thuyết SAI'}")

section("3) Thống kê x_auto_print_requested trên các phiếu PICK")
pick_domain = [
    ('picking_type_id.sequence_code', 'ilike', 'PICK'),
    ('return_id', '=', False),
]
assigned_no_flag = Picking.search_count(pick_domain + [
    ('state', '=', 'assigned'), ('x_auto_print_requested', '=', False),
])
assigned_flag = Picking.search_count(pick_domain + [
    ('state', '=', 'assigned'), ('x_auto_print_requested', '=', True),
])
ever_flag = Picking.search_count(pick_domain + [('x_auto_print_requested', '=', True)])
print(f"  PICK đang 'assigned', CHƯA từng tự động gửi in : {assigned_no_flag}")
print(f"  PICK đang 'assigned', ĐÃ tự động gửi in        : {assigned_flag}")
print(f"  PICK (mọi state) đã tự động gửi in             : {ever_flag}")
flagged = Picking.search(pick_domain + [('x_auto_print_requested', '=', True)],
                         order='id desc', limit=10)
if flagged:
    print("  10 phiếu gần nhất có cờ (để đối chiếu xem có phải do chạy tay force_auto_print_test.py):")
    for p in flagged:
        print(f"    {p.name:20s} state={p.state:10s} write_date={p.write_date}")
else:
    print("  KHÔNG có phiếu nào từng được tự động gửi in -> rất nghiêng về giả thuyết hook chưa bao giờ chạy.")

section(f"4) Đơn {ORDER_NAME} — trạng thái thực tế")
so = env['sale.order'].sudo().search([('name', '=', ORDER_NAME)], limit=1)  # noqa: F821
if not so:
    print(f"  Không tìm thấy đơn {ORDER_NAME!r}")
else:
    picks = so.picking_ids.filtered(
        lambda p: 'PICK' in (p.picking_type_id.sequence_code or '').upper() and not p.return_id
    )
    for p in picks:
        wh = p.picking_type_id.warehouse_id
        print(f"  {p.name} state={p.state!r} x_auto_print_requested={p.x_auto_print_requested} "
              f"x_pick_delivery_type={p.x_pick_delivery_type!r} kho={wh.name if wh else '(?)'}")
    qs = Queue.search(['|', ('sale_order_id', '=', so.id), ('picking_ids', 'in', picks.ids)])
    if not qs:
        print("  -> KHÔNG có bản ghi hàng chờ in nào cho đơn này (kể cả lỗi/hủy).")
    for q in qs:
        print(f"  -> queue #{q.id} state={q.state!r} warehouse_action={q.warehouse_action!r} "
              f"verify={q.verify_state!r} err={q.error_message!r} requested_at={q.requested_at}")

section(f"5) Kho {WAREHOUSE_CODE} — có in ra giấy được không (mắt thứ 3 của luồng)")
wh = env['stock.warehouse'].sudo().search([('code', '=ilike', WAREHOUSE_CODE)], limit=1)  # noqa: F821
if not wh:
    print(f"  Không tìm thấy kho mã {WAREHOUSE_CODE!r}")
else:
    device = wh.x_iot_printer_device_id
    print(f"  Kho: {wh.name} (id={wh.id})")
    print(f"  Máy in IoT      : {device.name if device else '(CHƯA GÁN — _do_print() sẽ báo lỗi ngay)'}"
          f"{'  connected=%s' % device.connected if device else ''}")
    print(f"  Report riêng    : {wh.x_iot_report_id.name if wh.x_iot_report_id else '(dùng mẫu mặc định theo tên)'}")
    print(f"  Giới hạn hàng chờ: {wh.x_iot_queue_limit} (0 = không giới hạn), "
          f"đang hoạt động: {Queue.count_active_for_warehouse(wh.id)}")
    print(f"  Watchdog máy kho : last_seen={wh.x_iot_watchdog_last_seen} service_ok={wh.x_iot_watchdog_service_ok} "
          f"note={(wh.x_iot_watchdog_note or '')[:60]!r}")
    print("  -> last_seen rỗng/rất cũ = script watchdog ở máy kho KHÔNG chạy, nên đường 'máy kho in")
    print("     thẳng' không tiêu thụ hàng chờ; lúc đó chỉ còn trông vào dashboard đang mở.")
    pend = Queue.search([('warehouse_id', '=', wh.id), ('state', 'in', ('pending', 'printing'))],
                        order='requested_at asc', limit=20)
    print(f"\n  Hàng chờ đang pending/printing: {len(pend)}")
    for q in pend:
        print(f"    #{q.id} {q.sale_order_id.name:22s} state={q.state:9s} action={q.warehouse_action:9s} "
              f"requested_at={q.requested_at}")
    errs = Queue.search([('warehouse_id', '=', wh.id), ('state', '=', 'error')],
                        order='id desc', limit=10)
    print(f"\n  10 bản ghi lỗi gần nhất: {len(errs)}")
    for q in errs:
        print(f"    #{q.id} {q.sale_order_id.name:22s} {(q.error_message or '')[:90]}")
    susp = Queue.search([('warehouse_id', '=', wh.id), ('verify_state', '=', 'suspect')],
                        order='id desc', limit=10)
    print(f"\n  Bản ghi 'NGHI CHƯA IN RA' (đã gửi lệnh nhưng máy in không xác nhận): {len(susp)}")
    for q in susp:
        print(f"    #{q.id} {q.sale_order_id.name:22s} {(q.verify_note or '')[:90]}")

section("ĐỌC KẾT QUẢ")
print("  - Phần 2 = COMPUTE+STORE và phần 3 gần như không có phiếu nào có cờ")
print("    -> hook auto-print chưa từng chạy: phải chuyển trigger sang stock.move._action_assign()")
print("       (đường duy nhất mọi lần giữ hàng đều đi qua) và/hoặc thêm cron soát lại phiếu")
print("       'assigned' chưa gửi. Sửa setting/restart worker KHÔNG giải quyết được.")
print("  - Phần 3 có nhiều phiếu mang cờ -> hook CÓ chạy, đọc phần 4/5 để tìm mắt đang đứt:")
print("    chưa gán máy in IoT, hàng chờ đầy, hoặc không ai tiêu thụ hàng chờ (watchdog không")
print("    chạy + không có dashboard nào mở).")
