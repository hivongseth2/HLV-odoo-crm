# -*- coding: utf-8 -*-
"""
check_iot_watchdog_status.py
=================================
Kiểm tra nhanh tình trạng giám sát máy in IoT / máy chủ kho sau khi cài watchdog:
  1. Cấu hình: token watchdog đã đặt chưa, ngưỡng im lặng bao nhiêu phút, thời gian chờ đối chiếu,
     có tự động gửi lại lệnh in khi phát hiện phiếu chưa in không, email cảnh báo là ai.
  2. Từng kho có máy in IoT: Odoo có thấy hộp IoT không (iot.device.connected), máy chủ kho có
     gửi heartbeat về không (x_iot_watchdog_last_seen), service ở kho có đang chạy không, và
     KẾT LUẬN gộp (overall_ok) đúng như chip trạng thái hiện trên dashboard/sale_plan.
  3. ĐỐI CHIẾU 2 HÀNG ĐỢI: số tờ máy in Windows đã in thật (bộ đếm gửi kèm heartbeat) so với số
     lệnh in Odoo đã gửi — liệt kê CHI TIẾT mọi phiếu bị nghi "đã gửi mà chưa ra giấy".
  4. Hàng chờ in đang tồn: bao nhiêu bản ghi 'pending'/'printing'/'error' — nếu pending dồn nhiều
     mà không giảm thì thường là KHÔNG có phiên dashboard backend nào đang mở để dispatch in.

CHỈ ĐỌC — không write/create/unlink gì.

Chạy bằng lệnh (trên Odoo.sh shell):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_iot_watchdog_status.py
"""

from odoo import fields

SEP = "=" * 100
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

ICP = env['ir.config_parameter'].sudo()
Queue = env['hlv.iot.print.queue'].sudo()
Warehouse = env['stock.warehouse'].sudo()

section("1) Cấu hình watchdog")
token = ICP.get_param('hlv_sale_delivery_planning.iot_watchdog_token') or ''
silence = ICP.get_param('hlv_sale_delivery_planning.iot_watchdog_max_silence_minutes') or '(mặc định 5)'
grace = ICP.get_param('hlv_sale_delivery_planning.iot_verify_grace_minutes') or '(mặc định 5)'
stale = ICP.get_param('hlv_sale_delivery_planning.iot_pending_stale_minutes') or '(mặc định 10)'
auto_requeue = ICP.get_param('hlv_sale_delivery_planning.iot_auto_requeue_unprinted')
emails = ICP.get_param('hlv_sale_delivery_planning.iot_alert_emails') or '(chưa đặt — chỉ cảnh báo trên dashboard)'
print(f"  token đã đặt: {'CÓ (%d ký tự)' % len(token) if token else 'CHƯA — endpoint heartbeat sẽ từ chối mọi tín hiệu'}")
print(f"  ngưỡng im lặng (phút): {silence}")
print(f"  thời gian chờ trước khi đối chiếu (phút): {grace}")
print(f"  yêu cầu in chờ quá bao nhiêu phút thì báo động: {stale}")
print(f"  tự gửi lại lệnh in khi nghi chưa in: {'BẬT' if auto_requeue in ('True', 'true', '1') else 'TẮT (chỉ cảnh báo, kho tự bấm gửi lại)'}")
print(f"  email nhận cảnh báo: {emails}")

section("2) Từng kho có máy in IoT")
rows = Queue.get_printer_status_by_warehouse()
if not rows:
    print("  Chưa kho nào được gán máy in IoT (stock.warehouse.x_iot_printer_device_id).")
for r in rows:
    print(f"\n  --- {r['warehouse_name']} (id={r['warehouse_id']}) ---")
    print(f"    máy in                 : {r['device_name']}")
    print(f"    Odoo thấy hộp IoT      : {'CÓ' if r['connected'] else 'KHÔNG'} "
          f"(device.write_date={r['last_seen'] or 'không rõ'})")
    if r['watchdog_installed']:
        print(f"    watchdog máy chủ kho   : lần cuối báo về {r['watchdog_last_seen']}, "
              f"service {'Running' if r['watchdog_service_ok'] else 'KHÔNG chạy'}")
        print(f"    ghi chú từ máy chủ kho : {r['watchdog_note'] or '(không có)'}")
    else:
        print("    watchdog máy chủ kho   : CHƯA CÀI (không giám sát) — xem bin/iot_watchdog_windows.ps1")
    print(f"    => KẾT LUẬN            : {'OK, in được' if r['overall_ok'] else 'CÓ SỰ CỐ: ' + r['problem_message']}")

section("3) Đối chiếu 2 hàng đợi (Odoo đã gửi vs máy in đã in thật)")
verify_labels = {
    'waiting': 'chờ đối chiếu',
    'printed_ok': 'máy in xác nhận ĐÃ IN',
    'suspect': 'NGHI CHƯA IN RA GIẤY',
    'no_data': 'không đối chiếu được (thiếu số liệu bộ đếm)',
}
for wh in Warehouse.search([('x_iot_printer_device_id', '!=', False)]):
    print(f"\n  --- {wh.name} ---")
    log = wh._iot_read_counter_log()
    if not log:
        print("    bộ đếm máy in          : CHƯA CÓ SỐ LIỆU — watchdog ở kho chưa gửi 'printed_total'")
        print("                             (cần bản .ps1 mới nhất trong bin/iot_watchdog_windows.ps1)")
    else:
        first_ts, first_val = log[0]
        last_ts, last_val = log[-1]
        print(f"    bộ đếm máy in          : {len(log)} mốc, từ {first_ts} (={first_val}) "
              f"đến {last_ts} (={last_val})")
        print(f"    số tờ đã in trong dải  : {max(last_val - first_val, 0)}")
    for vstate, label in verify_labels.items():
        cnt = Queue.search_count([('warehouse_id', '=', wh.id), ('state', '=', 'printed'),
                                  ('verify_state', '=', vstate)])
        if cnt:
            print(f"    {label:<45s}: {cnt}")
    suspects = Queue.search([('warehouse_id', '=', wh.id), ('verify_state', '=', 'suspect')],
                            order='printed_at desc', limit=20)
    if suspects:
        print(f"\n    !!! {len(suspects)} PHIẾU NGHI CHƯA IN RA GIẤY (mới nhất trước) — kho cần gửi lại lệnh in:")
        for s in suspects:
            print(f"      - đơn {s.sale_order_id.name or '?'} | gửi lệnh in lúc {s.printed_at} "
                  f"| đối chiếu lúc {s.verified_at} | trạng thái hiện tại: {s.state}")
            if s.verify_note:
                print(f"          {s.verify_note}")
        print("      => Mở dashboard 'Điều phối Giao hàng', bấm 'Gửi lại lệnh in ngay' trên khối đỏ,")
        print("         hoặc bật 'Tự gửi lại lệnh in' trong Cấu hình để Odoo tự làm.")
    else:
        print("    => Không có phiếu nào bị nghi chưa in ra giấy.")

section("4) Hàng chờ in đang tồn")
for state in ('pending', 'printing', 'error'):
    count = Queue.search_count([('state', '=', state), ('warehouse_action', '=', 'none')])
    print(f"  {state:9s}: {count}")
for wh in Warehouse.search([('x_iot_printer_device_id', '!=', False)]):
    stuck = wh._iot_pending_stuck()
    if not stuck:
        continue
    oldest_min = int((fields.Datetime.now() - stuck[0].requested_at).total_seconds() / 60)
    print(f"  !!! {wh.name}: {len(stuck)} yêu cầu in NẰM CHỜ chưa được gửi xuống máy in "
          f"(cũ nhất {oldest_min} phút)")
    for q in stuck[:10]:
        print(f"      - đơn {q.sale_order_id.name or '?'} | sale yêu cầu lúc {q.requested_at}")
    print("      => Lệnh in được đẩy xuống hộp IoT bởi TRÌNH DUYỆT đang mở trang 'Điều phối")
    print("         Giao hàng' — server không vào được LAN kho nên KHÔNG tự gửi được. Không ai")
    print("         mở trang đó thì hàng chờ nằm im vô thời hạn; dữ liệu KHÔNG mất, mở lên là in.")
    print("         Odoo đã cảnh báo: chip đỏ trên dashboard + email + popup ngay tại máy kho.")

print(f"\n  (thời điểm kiểm tra: {fields.Datetime.now()} UTC)")
section("XONG")
