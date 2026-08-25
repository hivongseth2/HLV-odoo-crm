# -*- coding: utf-8 -*-
"""
check_auto_print_when_full.py
==================================
Đơn DH125524949235630 / phiếu KBC/PICK/11494: phiếu đã "Sẵn sàng" (state=assigned, SL yêu cầu ==
SL thực tế cho cả 2 dòng — đủ hàng 100%) nhưng KHÔNG thấy trong hàng chờ in IoT
(hlv.iot.print.queue) dù setting "Tự động gửi in khi phiếu đủ hàng"
(auto_print_pick_slip_when_full) được kỳ vọng đã bật.

Script này kiểm tra lần lượt các nguyên nhân khả dĩ (theo đúng logic trong
models/stock_picking.py:_auto_queue_print_when_full() và
services/delivery_planner_iot_print.py:auto_confirm_print_pick_slip()):
  1. Setting auto_print_pick_slip_when_full có thực sự đang BẬT không.
  2. Setting lock_pick_slip_requests (khóa tạm tính năng) có đang BẬT không — nếu có, auto-print
     cũng bị chặn giống sale bấm tay.
  3. Field x_auto_print_requested trên phiếu này đã = True chưa — NẾU đã True mà không có gì
     trong queue, nghĩa là lần tự động gửi ĐẦU TIÊN đã bị chặn (khóa tính năng / kho đầy queue /
     không xác định được đơn hàng) và theo thiết kế hiện tại sẽ KHÔNG tự thử lại nữa (chỉ tự
     động gửi ĐÚNG 1 LẦN cho mỗi phiếu, xem comment trong _auto_queue_print_when_full).
  4. Kho của phiếu có cấu hình x_iot_queue_limit chặn không (đã đầy hàng chờ lúc đó).
  5. hlv.iot.print.queue có bản ghi nào cho đơn/phiếu này không (kể cả đã hủy/lỗi).

CHỈ ĐỌC — không write/create/unlink gì.

Chạy bằng lệnh (trên Odoo.sh shell):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_auto_print_when_full.py
"""

ORDER_NAME = "DH125524949235630"  # đổi nếu cần
PICKING_NAME = "KBC/PICK/11494"  # đổi nếu cần

SEP = "=" * 100
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

ICP = env['ir.config_parameter'].sudo()

section("1) Setting liên quan")
auto_param = ICP.get_param('hlv_sale_delivery_planning.auto_print_pick_slip_when_full', default='(chưa set)')
lock_param = ICP.get_param('hlv_sale_delivery_planning.lock_pick_slip_requests', default='(chưa set)')
print(f"  auto_print_pick_slip_when_full = {auto_param!r}")
print(f"  lock_pick_slip_requests        = {lock_param!r}")
auto_on = str(auto_param) in ('1', 'True', 'true')
lock_on = str(lock_param) in ('1', 'True', 'true')
print(f"  -> auto-print ĐANG {'BẬT' if auto_on else 'TẮT — đây có thể là lý do, cần vào Settings bật lên'}")
if lock_on:
    print(f"  -> CẢNH BÁO: lock_pick_slip_requests ĐANG BẬT — auto-print sẽ bị chặn hoàn toàn dù setting kia bật.")

so = env['sale.order'].sudo().search([('name', '=', ORDER_NAME)], limit=1)
if not so:
    print(f"\n  Không tìm thấy đơn {ORDER_NAME!r}")
else:
    section(f"2) Đơn {so.name} (id={so.id})")
    pick = env['stock.picking'].sudo().search([('name', '=', PICKING_NAME)], limit=1)
    if not pick:
        pick = so.picking_ids.filtered(lambda p: 'PICK' in (p.picking_type_id.sequence_code or '').upper())[:1]
    if not pick:
        print(f"  Không tìm thấy phiếu {PICKING_NAME!r} / không có phiếu PICK nào cho đơn này.")
    else:
        print(f"  Phiếu: {pick.name} (id={pick.id}) state={pick.state}")
        print(f"  x_auto_print_requested = {pick.x_auto_print_requested}")
        wh = pick.picking_type_id.warehouse_id
        print(f"  Kho: {wh.name if wh else '(không xác định)'}  x_iot_queue_limit={wh.x_iot_queue_limit if wh else '?'}")
        print("\n  -- Từng move (SL yêu cầu vs SL thực tế / reserved) --")
        for mv in pick.move_ids.sorted('id'):
            print(f"    move #{mv.id} {mv.product_id.display_name[:40]:40s} "
                  f"demand={mv.product_uom_qty:>8.2f} reserved_availability={mv.reserved_availability:>8.2f} "
                  f"state={mv.state}")

        section("3) hlv.iot.print.queue liên quan đơn/phiếu này")
        Queue = env['hlv.iot.print.queue'].sudo()
        by_so = Queue.search([('sale_order_id', '=', so.id)])
        by_pick = Queue.search([('picking_ids', 'in', [pick.id])])
        all_q = by_so | by_pick
        if not all_q:
            print("  KHÔNG có bản ghi hàng chờ in nào (kể cả hủy/lỗi) cho đơn/phiếu này.")
        for q in all_q:
            print(f"    queue #{q.id} state={q.state!r} warehouse_action={q.warehouse_action!r} "
                  f"error_message={q.error_message!r} requested_at={q.requested_at} "
                  f"pickings={q.picking_ids.mapped('name')}")

        section("4) Nhật ký chatter của phiếu (state changes gần đây)")
        msgs = env['mail.message'].sudo().search([
            ('model', '=', 'stock.picking'), ('res_id', '=', pick.id),
        ], order='date desc', limit=15)
        for m in msgs:
            body_txt = (m.body or '').replace('\n', ' ')[:150]
            print(f"    {m.date}  {body_txt}")

section("KẾT LUẬN GỢI Ý")
print("  - Nếu auto_print_pick_slip_when_full = TẮT -> vào Settings > HLV Delivery Planner bật lên.")
print("  - Nếu lock_pick_slip_requests = BẬT -> tắt khóa này thì auto-print mới chạy được.")
print("  - Nếu x_auto_print_requested = True nhưng KHÔNG có gì trong queue -> lần tự động gửi")
print("    ĐẦU TIÊN (có thể lúc phiếu 'Sẵn sàng' sớm hơn, trước khi bật setting hoặc trong lúc")
print("    đang khóa) đã bị chặn và bị đánh dấu 'đã thử' — theo thiết kế hiện tại sẽ KHÔNG tự")
print("    động thử lại. Cần bấm gửi in TAY 1 lần cho phiếu này (hoặc mình sửa lại logic để cho")
print("    phép thử lại khi chỉ bị chặn bởi khóa tạm/kho đầy, không tính là 'đã thử thật').")
