# -*- coding: utf-8 -*-
"""
check_iot_device_fields.py
=============================
Tìm field thật trên iot.device/iot.box dùng để biết máy in có ONLINE hay không TRƯỚC KHI
gửi lệnh in — hiện tại code (iot_print_queue.py._do_print) gửi lệnh mù, không kiểm tra máy
in có đang kết nối hay không trước khi dispatch report_action().

CHỈ ĐỌC — không write/create/unlink gì.

Chạy bằng lệnh (trên Odoo.sh shell):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_iot_device_fields.py
"""

SEP = "=" * 90
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

section("1. Các field của iot.device")
device_fields = env['iot.device']._fields
for name, f in sorted(device_fields.items()):
    print(f"  {name:30s} type={f.type:12s} store={getattr(f, 'store', '?')}")

section("2. Các field của iot.box")
box_fields = env['iot.box']._fields
for name, f in sorted(box_fields.items()):
    print(f"  {name:30s} type={f.type:12s} store={getattr(f, 'store', '?')}")

section("3. Máy in Brother thực tế (record hiện có)")
printers = env['iot.device'].sudo().search([('type', '=', 'printer')])
for p in printers:
    vals = p.read()[0]
    print(f"  --- device #{p.id}: {p.name!r} ---")
    for k, v in vals.items():
        print(f"    {k}: {v}")

section("4. IoT Box tương ứng")
boxes = printers.mapped('iot_id')
for b in boxes:
    vals = b.read()[0]
    print(f"  --- box #{b.id}: {b.name!r} ---")
    for k, v in vals.items():
        print(f"    {k}: {v}")

section("XONG — tìm field kiểu boolean/datetime liên quan 'connect'/'online'/'seen'/'ping'/'status'")
