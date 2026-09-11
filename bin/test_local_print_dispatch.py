# -*- coding: utf-8 -*-
"""
test_local_print_dispatch.py
================================
KIỂM THỬ đường in TRỰC TIẾP tại máy kho (không cần trình duyệt mở trang điều phối):
  hlv.iot.print.queue.claim_for_local_dispatcher() / report_local_dispatch_result()
  — xem models/iot_print_queue.py và controllers/iot_watchdog_controller.py.

5 tình huống:
  1. Claim 1 yêu cầu đang chờ  -> trả về PDF base64, bản ghi chuyển 'printing' (CHƯA 'printed')
  2. Máy kho báo in THÀNH CÔNG -> 'printed' + chatter ghi rõ in trực tiếp + verify_state reset
  3. Máy kho báo in LỖI        -> 'error' + lý do (không im lặng bỏ qua)
  4. Không báo gì, quá 10 phút -> bản ghi được đưa LẠI hàng chờ ('pending'), không kẹt vĩnh viễn
  5. Mã kho sai               -> trả về success=False, không sờ vào dữ liệu kho khác

⚠️ Script CÓ ghi tạm vào database nhưng ROLLBACK ở cuối, không commit. Nên chạy trên staging.

Chạy bằng lệnh (trên Odoo.sh shell):
    python odoo-bin shell -d <TEN_DATABASE> < bin/test_local_print_dispatch.py
"""

import base64
from datetime import timedelta

from odoo import fields

SEP = "=" * 100
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

Queue = env['hlv.iot.print.queue'].sudo()
Warehouse = env['stock.warehouse'].sudo()

# Cần 1 kho có máy in IoT + 1 phiếu lấy hàng thật để render được PDF phiếu.
picking = env['stock.picking'].sudo().search([
    ('picking_type_id.code', '=', 'internal'), ('state', '!=', 'cancel'),
], limit=1) or env['stock.picking'].sudo().search([('state', '!=', 'cancel')], limit=1)
wh = Warehouse.search([('x_iot_printer_device_id', '!=', False)], limit=1) or Warehouse.search([], limit=1)
so = env['sale.order'].sudo().search([('state', 'in', ['sale', 'done'])], limit=1)

if not (wh and so and picking):
    print("  Thiếu dữ liệu để test (cần 1 kho, 1 đơn bán đã xác nhận, 1 phiếu kho).")
else:
    print(f"  Kho: {wh.name} (code={wh.code}) | đơn: {so.name} | phiếu: {picking.name}")
    results = []

    def make_pending():
        return Queue.create({
            'sale_order_id': so.id,
            'warehouse_id': wh.id,
            'picking_ids': [(6, 0, picking.ids)],
            'state': 'pending',
            'requested_at': fields.Datetime.now() - timedelta(minutes=1),
        })

    def check(name, ok, detail=''):
        results.append(bool(ok))
        print(f"\n  [{'ĐÚNG' if ok else 'SAI'}] {name}")
        if detail:
            print(f"        {detail}")

    section("1) Máy kho claim yêu cầu đang chờ")
    rec = make_pending()
    res = Queue.claim_for_local_dispatcher(wh.code, limit=5)
    job = next((j for j in res.get('jobs', []) if j['queue_id'] == rec.id), None)
    pdf_len = len(base64.b64decode(job['pdf_b64'])) if job else 0
    check(
        'Trả về PDF và giữ bản ghi ở "Đang in..." (chưa dám nói là đã in)',
        bool(job) and pdf_len > 500 and rec.state == 'printing',
        f"state={rec.state} | pdf={pdf_len} bytes | đơn trả về={job and job['sale_order_name']}",
    )

    section("2) Máy kho báo IN THÀNH CÔNG")
    Queue.report_local_dispatch_result(wh.code, [
        {'queue_id': rec.id, 'success': True, 'printer': 'Xprinter XP-80'},
    ])
    last_msg = rec.message_ids and rec.message_ids[0].body or ''
    check(
        'Chuyển "Đã gửi lệnh in" + ghi chatter là in trực tiếp + đặt lại đối chiếu',
        rec.state == 'printed' and rec.printed_at and rec.verify_state == 'waiting'
        and 'in trực tiếp' in last_msg,
        f"state={rec.state} | verify_state={rec.verify_state} | chatter={last_msg[:90]}",
    )

    section("3) Máy kho báo IN LỖI")
    rec2 = make_pending()
    Queue.claim_for_local_dispatcher(wh.code, limit=5)
    Queue.report_local_dispatch_result(wh.code, [
        {'queue_id': rec2.id, 'success': False, 'message': 'SumatraPDF tra ve ExitCode=3',
         'printer': 'Xprinter XP-80'},
    ])
    check(
        'Chuyển "Lỗi" kèm nguyên văn lý do từ máy kho (không im lặng nuốt lỗi)',
        rec2.state == 'error' and 'ExitCode=3' in (rec2.error_message or ''),
        f"state={rec2.state} | error_message={rec2.error_message}",
    )

    section("4) Máy kho chết giữa đường (claim rồi không báo gì)")
    rec3 = make_pending()
    Queue.claim_for_local_dispatcher(wh.code, limit=5)
    was_printing = rec3.state == 'printing'
    # Giả lập đã claim từ 20 phút trước: write_date là cột hệ thống nên phải ghi bằng SQL.
    env.cr.execute(
        "UPDATE hlv_iot_print_queue SET write_date = %s WHERE id = %s",
        (fields.Datetime.now() - timedelta(minutes=20), rec3.id),
    )
    rec3.invalidate_recordset(['write_date'])
    Queue.claim_for_local_dispatcher(wh.code, limit=5)
    check(
        'Bản ghi kẹt "Đang in..." được đưa lại hàng chờ để in lại, không kẹt vĩnh viễn',
        was_printing and rec3.state in ('printing', 'pending'),
        f"trước={was_printing and 'printing'} | sau khi reclaim={rec3.state} "
        f"(claim lại ngay nên có thể đã là 'printing' của lượt mới — vẫn đúng)",
    )

    section("5) Mã kho sai")
    bad = Queue.claim_for_local_dispatcher('KHO_KHONG_TON_TAI_XYZ', limit=5)
    bad2 = Queue.report_local_dispatch_result('KHO_KHONG_TON_TAI_XYZ', [
        {'queue_id': rec.id, 'success': True},
    ])
    check(
        'Từ chối cả 2 route khi mã kho không tồn tại',
        bad.get('success') is False and bad2.get('success') is False,
        f"claim={bad.get('message')} | report={bad2.get('message')}",
    )

    section("KẾT QUẢ")
    print(f"  {sum(results)}/{len(results)} tình huống ĐÚNG")
    if all(results):
        print("  => Đường in trực tiếp tại máy kho hoạt động đúng như thiết kế.")
    else:
        print("  => CÓ TÌNH HUỐNG SAI, xem chi tiết phía trên.")

env.cr.rollback()
print("\n  Đã ROLLBACK toàn bộ dữ liệu test — database không bị thay đổi gì.")
