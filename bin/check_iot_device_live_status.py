# -*- coding: utf-8 -*-
"""
check_iot_device_live_status.py
===================================
User đã DỪNG service Odoo/hw_drivers trên máy IoT Box local (ThanhLuanLapTop, box #9) để test,
nhưng iot.device.connected vẫn báo True — xác nhận field này là "trạng thái báo cáo lần cuối",
KHÔNG có timeout tự động. Script này in ra connected + write_date + "đã im lặng bao lâu" cho
TẤT CẢ máy in, để xem thực tế write_date có bị đứng lại (không cập nhật) trong khi connected
vẫn giữ True hay không — xác nhận đúng cơ chế trước khi sửa logic detect offline.

CHỈ ĐỌC — không write/create/unlink gì.

Chạy bằng lệnh (trên Odoo.sh shell, hoặc chạy tại chính Odoo local đang chạy IoT test):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_iot_device_live_status.py
"""

from datetime import datetime, timezone

SEP = "=" * 90
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

now_utc = datetime.now(timezone.utc)
print(f"  Giờ hiện tại (UTC): {now_utc.strftime('%Y-%m-%d %H:%M:%S')}")

section("Trạng thái iot.device (loại printer)")
printers = env['iot.device'].sudo().search([('type', '=', 'printer')])
for p in printers:
    if not p.write_date:
        age_str = 'không rõ'
    else:
        age = now_utc - p.write_date.replace(tzinfo=timezone.utc)
        age_str = f"{age.total_seconds():.0f}s trước ({age})"
    print(f"  #{p.id:4d} {p.name:35s} box={p.iot_id.name or '?':25s} "
          f"connected={p.connected!s:5s} write_date={p.write_date} (im lặng: {age_str})")

section("Trạng thái iot.box")
boxes = env['iot.box'].sudo().search([])
for b in boxes:
    if not b.write_date:
        age_str = 'không rõ'
    else:
        age = now_utc - b.write_date.replace(tzinfo=timezone.utc)
        age_str = f"{age.total_seconds():.0f}s trước"
    print(f"  #{b.id:4d} {b.name:30s} ip={b.ip or '?':16s} write_date={b.write_date} (im lặng: {age_str})")

section("XONG")
print("  Nếu box/device bạn vừa tắt có 'im lặng' > vài phút mà connected vẫn True -> xác nhận")
print("  đúng: connected không tự hết hạn, phải tự kiểm tra write_date để suy ra offline thật.")
