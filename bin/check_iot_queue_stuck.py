# -*- coding: utf-8 -*-
"""
check_iot_queue_stuck.py
=========================
Máy kho log ra hai dòng lỗi lặp đi lặp lại, xen kẽ với heartbeat bình thường:

    [ERROR] Odoo bao co 1 yeu cau in dang NAM CHO chua duoc gui xuong may in —
            duong in truc tiep dang bat nhung chua in duoc chung
    [ERROR] Odoo phát hiện 1 phiếu ĐÃ GỬI LỆNH IN nhưng máy in KHÔNG in ra giấy

Trong khi vòng lặp watchdog vẫn chạy đúng nhịp 2 phút và vẫn in được phiếu khác
(in_truc_tiep=2, da_in_tong tăng 15 -> 17). Nghĩa là KHÔNG phải watchdog chết, mà có phiếu
cụ thể không được nhận — hoặc nhận rồi mà máy in không nhả giấy.

Script này in ra đúng những bản ghi đó kèm mốc thời gian, để biết phiếu nào kẹt và kẹt bao
lâu. Đối chiếu 2 tập hợp:
  - Tập CLAIM của máy kho  (iot_print_queue.claim_for_local_dispatcher)
  - Tập ĐẾM "nằm chờ"      (stock_warehouse._iot_pending_stuck)
Hai tập này phải khớp domain; lệch nhau là gốc của cảnh báo ma.

CHỈ ĐỌC — không write/create/unlink gì.

Chạy bằng lệnh (trên Odoo.sh shell):
    python odoo-bin shell -d <TEN_DATABASE> --no-http < bin/check_iot_queue_stuck.py
"""

MA_KHO = 'KBC'  # đổi nếu soi kho khác

SEP = "=" * 100


def section(t):
    print(f"\n{SEP}\n  {t}\n{SEP}")


from odoo import fields as odoo_fields

Queue = env['hlv.iot.print.queue'].sudo()  # noqa: F821
Warehouse = env['stock.warehouse'].sudo()  # noqa: F821
now = odoo_fields.Datetime.now()

wh = Warehouse.search([('code', '=ilike', MA_KHO)], limit=1)
if not wh:
    print(f"  Không tìm thấy kho mã {MA_KHO!r}")
else:
    section(f"1) Ngưỡng và cấu hình của kho {wh.name}")
    stale = wh._iot_pending_stale_minutes()
    print(f"  Ngưỡng coi là 'nằm chờ quá lâu' : {stale} phút")
    print(f"  Máy in IoT gán cho kho          : {wh.x_iot_printer_device_id.name or '(chưa gán)'}")
    print(f"  Mẫu phiếu riêng của kho         : {wh.x_iot_report_id.name or '(mặc định theo tên)'}")
    print(f"  Watchdog lần cuối báo về        : {wh.x_iot_watchdog_last_seen}")
    print(f"  Giờ máy chủ Odoo hiện tại       : {now}")

    section("2) Phiếu đang PENDING — máy kho ĐÁNG LẼ phải nhận được")
    # Đúng domain của claim_for_local_dispatcher.
    pending = Queue.search([
        ('warehouse_id', '=', wh.id),
        ('state', '=', 'pending'),
        ('warehouse_action', '=', 'none'),
    ], order='requested_at asc, id asc')
    print(f"  Số bản ghi claim được: {len(pending)}")
    for q in pending:
        tuoi = (now - q.requested_at).total_seconds() / 60.0 if q.requested_at else -1
        print(f"    #{q.id:<5} {q.sale_order_id.name:<22} yêu cầu {q.requested_at} "
              f"({tuoi:.1f} phút trước)  phiếu={q.picking_ids.mapped('name')}")
        if not q.picking_ids:
            print("           ^-- KHÔNG có phiếu nào gắn vào: claim xong sẽ bị đẩy sang 'error'")

    section("3) Phiếu bị ĐẾM là 'nằm chờ quá lâu' (nguồn của dòng ERROR trên máy kho)")
    stuck = wh._iot_pending_stuck()
    print(f"  Số bản ghi: {len(stuck)}")
    for q in stuck:
        tuoi = (now - q.requested_at).total_seconds() / 60.0 if q.requested_at else -1
        print(f"    #{q.id:<5} {q.sale_order_id.name:<22} chờ {tuoi:.1f} phút")
    # Hai tập phải TRÙNG NHAU (stuck là tập con của pending, chỉ thêm điều kiện đủ cũ).
    lech = stuck - pending
    if lech:
        print("\n  BẤT THƯỜNG: có bản ghi bị đếm 'nằm chờ' mà KHÔNG nằm trong tập claim được:")
        for q in lech:
            print(f"    #{q.id} state={q.state!r} warehouse_action={q.warehouse_action!r}")
        print("  -> Cảnh báo ma: máy kho bị mắng vì phiếu mà chính nó không có quyền nhận.")

    section("4) Phiếu đang kẹt ở 'Đang in...' (claim rồi nhưng chưa báo kết quả)")
    printing = Queue.search([('warehouse_id', '=', wh.id), ('state', '=', 'printing')],
                            order='write_date asc')
    print(f"  Số bản ghi: {len(printing)}")
    for q in printing:
        tuoi = (now - q.write_date).total_seconds() / 60.0 if q.write_date else -1
        print(f"    #{q.id:<5} {q.sale_order_id.name:<22} kẹt {tuoi:.1f} phút "
              f"(quá 10 phút thì Odoo tự đưa lại về hàng chờ)")

    section("5) Phiếu 'NGHI CHƯA IN RA' — đã gửi lệnh mà máy in không xác nhận")
    suspect = Queue.search([('warehouse_id', '=', wh.id), ('verify_state', '=', 'suspect')],
                           order='id desc', limit=15)
    print(f"  Số bản ghi: {len(suspect)}")
    for q in suspect:
        print(f"    #{q.id:<5} {q.sale_order_id.name:<22} in lúc {q.printed_at}")
        print(f"           {(q.verify_note or '')[:100]}")

    section("6) 10 phiếu gần nhất — xem ĐỘ TRỄ thật từ lúc yêu cầu tới lúc in")
    gan_day = Queue.search([('warehouse_id', '=', wh.id), ('printed_at', '!=', False)],
                           order='printed_at desc', limit=10)
    print(f"  {'#':<6} {'Đơn':<22} {'Yêu cầu lúc':<20} {'In lúc':<20} {'Trễ (phút)':>11}")
    print(f"  {'-' * 86}")
    tre = []
    for q in gan_day:
        if not (q.requested_at and q.printed_at):
            continue
        phut = (q.printed_at - q.requested_at).total_seconds() / 60.0
        tre.append(phut)
        print(f"  {q.id:<6} {q.sale_order_id.name:<22} {str(q.requested_at):<20} "
              f"{str(q.printed_at):<20} {phut:>11.1f}")
    if tre:
        print(f"\n  Trễ trung bình {sum(tre) / len(tre):.1f} phút · nhanh nhất {min(tre):.1f} · "
              f"chậm nhất {max(tre):.1f}")
        print("  Watchdog quét mỗi 2 phút, nên trễ BÌNH THƯỜNG phải dưới ~3 phút.")
        print("  Trễ ~10 phút đều đặn = đang bị nhịp 10 phút của Task Scheduler quyết định,")
        print("  tức vòng lặp 2 phút không sống liên tục như log tưởng.")

section("ĐỌC KẾT QUẢ")
print("  - Phần 2 có bản ghi CŨ (chờ vài chục phút) mà phần 6 cho thấy phiếu khác vẫn in")
print("    đều -> không phải watchdog chết, mà đúng bản ghi đó có gì đó chặn: hay gặp nhất")
print("    là picking_ids RỖNG (claim xong là chuyển 'error', nhưng lượt sau lại thấy bản")
print("    ghi pending khác) hoặc render PDF lỗi.")
print("  - Phần 3 lệch phần 2 -> cảnh báo ma: sửa domain cho hai chỗ khớp nhau.")
print("  - Phần 4 có bản ghi kẹt 'Đang in...' lâu -> máy kho claim rồi CHẾT trước khi báo")
print("    kết quả; Odoo sẽ tự đưa lại sau 10 phút, và đó CHÍNH LÀ độ trễ ~10 phút thấy được.")
print("  - Phần 6 là câu trả lời thẳng cho 'sao 10 phút mới in': nhìn cột Trễ.")
