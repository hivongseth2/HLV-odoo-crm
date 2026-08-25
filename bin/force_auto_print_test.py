# -*- coding: utf-8 -*-
"""
force_auto_print_test.py
=============================
Đơn DH125524949235630 / phiếu KBC/PICK/11494: đã "Sẵn sàng" (đủ hàng 100%, xác nhận qua
check_auto_print_when_full.py), setting auto_print_pick_slip_when_full đang BẬT, không bị khóa,
nhưng KHÔNG có bản ghi nào trong hàng chờ in IoT — nghi ngờ web worker đang chạy CHƯA load code
write() hook mới (models/stock_picking.py:_auto_queue_print_when_full) dù DB/config đã cập nhật.

Script này gọi TRỰC TIẾP đúng logic đó (giống hệt hook sẽ chạy) ngay trong tiến trình `odoo-bin
shell` hiện tại — tiến trình shell luôn đọc code MỚI NHẤT trên đĩa, không phụ thuộc worker web có
đang chạy code cũ hay không. Nếu lần gọi này THÀNH CÔNG (tạo được bản ghi hàng chờ), nghĩa là:
  - Logic code ĐÚNG, không phải bug.
  - Vấn đề là web worker (phục vụ request bấm nút thật) đang chạy code CŨ — cần deploy/restart lại.
Đồng thời giải quyết luôn cho đơn NÀY (không cần sale bấm tay) vì thực sự gọi tạo hàng chờ.

⚠️ KHÔNG CHỈ ĐỌC — script này SẼ TẠO bản ghi hlv.iot.print.queue nếu điều kiện đủ (đúng như hành
vi mong muốn của tính năng), và set x_auto_print_requested=True cho phiếu nếu thành công. Không
unlink/xóa gì.

Chạy bằng lệnh (trên Odoo.sh shell):
    python odoo-bin shell -d <TEN_DATABASE> < bin/force_auto_print_test.py
"""

PICKING_NAME = "KBC/PICK/11494"  # đổi nếu cần

SEP = "=" * 100
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

pick = env['stock.picking'].sudo().search([('name', '=', PICKING_NAME)], limit=1)
if not pick:
    print(f"  Không tìm thấy phiếu {PICKING_NAME!r}")
else:
    section(f"TRƯỚC: {pick.name} state={pick.state} x_auto_print_requested={pick.x_auto_print_requested}")

    section("Gọi trực tiếp _auto_queue_print_when_full() (code hiện tại trên đĩa)")
    pick._auto_queue_print_when_full()
    env.cr.commit()

    pick = env['stock.picking'].sudo().browse(pick.id)  # re-browse để đọc giá trị mới nhất
    section(f"SAU: x_auto_print_requested={pick.x_auto_print_requested}")

    Queue = env['hlv.iot.print.queue'].sudo()
    q = Queue.search([('picking_ids', 'in', [pick.id])])
    if q:
        for r in q:
            print(f"  -> ĐÃ TẠO/CÓ hàng chờ: queue #{r.id} state={r.state!r} "
                  f"warehouse={r.warehouse_id.name} pickings={r.picking_ids.mapped('name')}")
        print("\n  KẾT LUẬN: logic ĐÚNG — vấn đề là web worker đang phục vụ request thật đang")
        print("  chạy code CŨ (chưa load hook mới), không phải lỗi logic. Cần deploy/restart lại")
        print("  server để các phiếu SAU tự động hoạt động đúng mà không cần chạy tay thế này.")
    else:
        print("  -> VẪN KHÔNG có gì trong hàng chờ sau khi gọi trực tiếp — nghĩa là bị chặn bởi")
        print("     1 điều kiện nào đó trong chính logic (setting/khóa/kho/không xác định đơn)")
        print("     — không phải vấn đề code cũ. Xem lại _auto_queue_print_when_full/")
        print("     auto_confirm_print_pick_slip để biết chính xác lý do.")
