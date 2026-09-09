# -*- coding: utf-8 -*-
"""
check_iot_watchdog_status.py
=================================
Kiểm tra nhanh tình trạng giám sát máy in IoT / máy chủ kho sau khi cài watchdog:
  1. Cấu hình: token watchdog đã đặt chưa, ngưỡng im lặng bao nhiêu phút, email cảnh báo là ai.
  2. Từng kho có máy in IoT: Odoo có thấy hộp IoT không (iot.device.connected), máy chủ kho có
     gửi heartbeat về không (x_iot_watchdog_last_seen), service ở kho có đang chạy không, và
     KẾT LUẬN gộp (overall_ok) đúng như chip trạng thái hiện trên dashboard/sale_plan.
  3. Hàng chờ in đang tồn: bao nhiêu bản ghi 'pending'/'printing'/'error' — nếu pending dồn nhiều
     mà không giảm thì thường là KHÔNG có phiên dashboard backend nào đang mở để dispatch in.

CHỈ ĐỌC — không write/create/unlink gì.

Chạy bằng lệnh (trên Odoo.sh shell):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_iot_watchdog_status.py
"""

SEP = "=" * 100
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

ICP = env['ir.config_parameter'].sudo()

section("1) Cấu hình watchdog")
token = ICP.get_param('hlv_sale_delivery_planning.iot_watchdog_token') or ''
silence = ICP.get_param('hlv_sale_delivery_planning.iot_watchdog_max_silence_minutes') or '(mặc định 5)'
emails = ICP.get_param('hlv_sale_delivery_planning.iot_alert_emails') or '(chưa đặt — chỉ cảnh báo trên dashboard)'
print(f"  token đã đặt: {'CÓ (%d ký tự)' % len(token) if token else 'CHƯA — endpoint heartbeat sẽ từ chối mọi tín hiệu'}")
print(f"  ngưỡng im lặng (phút): {silence}")
print(f"  email nhận cảnh báo: {emails}")

section("2) Từng kho có máy in IoT")
Queue = env['hlv.iot.print.queue'].sudo()
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

section("3) Hàng chờ in đang tồn")
for state in ('pending', 'printing', 'error'):
    count = Queue.search_count([('state', '=', state), ('warehouse_action', '=', 'none')])
    print(f"  {state:9s}: {count}")
oldest = Queue.search([('state', '=', 'pending'), ('warehouse_action', '=', 'none')],
                      order='requested_at asc', limit=1)
if oldest:
    print(f"\n  Yêu cầu 'pending' cũ nhất: đơn {oldest.sale_order_id.name} (kho {oldest.warehouse_id.name}) "
          f"từ {oldest.requested_at}")
    print("  Nếu con số này cũ hơn vài phút: KHÔNG có phiên dashboard backend nào đang mở để")
    print("  dispatch lệnh in — hàng chờ vẫn giữ nguyên (không mất), sẽ in ngay khi mở lại")
    print("  trang 'Điều phối Giao hàng' trên máy có kết nối tới máy in.")

section("XONG")
