# -*- coding: utf-8 -*-
"""
probe_iot_heartbeat_interval.py
==================================
Sau khi thêm ngưỡng 60s (IOT_DEVICE_STALE_SECONDS) để suy ra máy in offline, máy in Brother
DCP-B7620DW ở kho Bến Cam ĐANG IN THẬT (hoạt động tốt) nhưng bị báo OFFLINE — nghĩa là
write_date của iot.device KHÔNG cập nhật mỗi ~60s như tôi giả định (đoán mò, chưa đo thật).

Script này lấy mẫu write_date của các device đang nghi vấn NHIỀU LẦN, cách nhau 20s, trong
~3 phút — để đo CHÍNH XÁC write_date thật cập nhật mỗi bao lâu khi máy đang hoạt động bình
thường, trước khi chọn lại ngưỡng đúng.

CHỈ ĐỌC — không write/create/unlink gì.

Chạy bằng lệnh (trên Odoo.sh shell, lúc máy in Bến Cam đang online/đang in bình thường):
    python odoo-bin shell -d <TEN_DATABASE> < bin/probe_iot_heartbeat_interval.py
"""

import time
from datetime import datetime, timezone

SEP = "=" * 90
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

# Lấy TẤT CẢ device đang nghi vấn (Bến Cam, Tân Sơn Nhì) qua field trên stock.warehouse —
# không hardcode tên, để đúng device thật đang được dùng.
warehouses = env['stock.warehouse'].sudo().search([('x_iot_printer_device_id', '!=', False)])
devices = warehouses.mapped('x_iot_printer_device_id')
wh_by_device = {wh.x_iot_printer_device_id.id: wh.name for wh in warehouses}

if not devices:
    print("  Không có kho nào gán máy in IoT (x_iot_printer_device_id) — không có gì để đo.")
else:
    section(f"Theo dõi write_date của {len(devices)} máy in trong ~3 phút (10 lần, mỗi 20s)")
    print(f"  {'time':>8} | " + " | ".join(f"{wh_by_device.get(d.id, d.name)[:22]:22s}" for d in devices))

    SAMPLES = 10
    INTERVAL = 20  # giây

    last_seen = {d.id: None for d in devices}
    for i in range(SAMPLES):
        # Phải invalidate cache + commit trước mỗi lần đọc — nếu không, ORM sẽ trả lại giá trị đã
        # cache từ vòng đầu (script chạy trong CÙNG 1 transaction/env suốt 3 phút), và transaction
        # cũ có thể không thấy commit mới từ box (chạy ở request/transaction khác).
        env.invalidate_all()
        env.cr.commit()
        now = datetime.now(timezone.utc)
        row = [f"{i * INTERVAL:>6}s"]
        for d in devices:
            wd = d.write_date
            changed = ''
            if wd and last_seen[d.id] and wd != last_seen[d.id]:
                changed = ' *MỚI*'
            last_seen[d.id] = wd
            age = (now - wd.replace(tzinfo=timezone.utc)).total_seconds() if wd else -1
            conn = 'On ' if d.connected else 'Off'
            row.append(f"{conn} age={age:6.1f}s{changed}".ljust(22))
        print(f"  " + " | ".join(row))
        if i < SAMPLES - 1:
            time.sleep(INTERVAL)

    section("XONG")
    print("  Cột '*MỚI*' đánh dấu lần write_date thực sự nhảy sang giá trị mới trong lúc theo dõi.")
    print("  Khoảng cách giữa 2 lần '*MỚI*' liên tiếp = đúng tần suất heartbeat thật của box.")
    print("  Nếu suốt 3 phút KHÔNG thấy '*MỚI*' nào dù máy đang in bình thường -> write_date")
    print("  không phải là tín hiệu heartbeat liên tục, cần đổi cách phát hiện offline khác.")
