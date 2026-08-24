# -*- coding: utf-8 -*-
"""
check_stock_picking_hold_buttons.py
===================================
Đang mở rộng tính năng "Giữ hàng theo Sale" (module website_public_inventory_18) để:
  1. Ẩn thêm 2 nút trên phiếu giữ hàng (is_stock_hold_picking=True): "In phiếu lấy hàng" và
     "In Tem Nhãn" — đã xác định "In Tem Nhãn" = button name="action_open_label_wizard" (module
     custom_picking_label), nhưng "In phiếu lấy hàng" KHÔNG tìm thấy trong bất kỳ module custom
     nào (grep toàn bộ custom_addons không ra) — nên nghi là button gốc của Odoo core, cần dò
     đúng attribute name="..." của nó.
  2. Xác nhận model stock.picking có thực sự tồn tại method `do_unreserve` hay không — đây là
     method bị nghi ngờ đứng sau hành động "Hủy dự trữ" (Unreserve) trong menu Actions (⋮) của
     phiếu kho, đã override thử trong models/stock_picking.py nhưng chưa có cách xác nhận chắc
     chắn tên method đúng ở bản Odoo này.

CHỈ ĐỌC — không write/create/unlink gì.

Chạy bằng lệnh (trên Odoo.sh shell, hoặc odoo-bin shell tại môi trường đang chạy):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_stock_picking_hold_buttons.py
"""
import re

SEP = "=" * 90
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

section("1. Model stock.picking có method 'do_unreserve' không?")
Picking = env['stock.picking']
for name in ('do_unreserve', 'action_cancel', 'button_validate'):
    print(f"  hasattr(stock.picking, '{name}') = {hasattr(Picking, name)}")

section("2. Tìm mọi method của stock.picking có tên chứa 'unreserve' (không phân biệt hoa/thường)")
for name in dir(Picking):
    if 'unreserve' in name.lower():
        print(f"  - {name}")

section("3. ARCH GỐC (raw, chưa compose qua inherit) của view stock.view_picking_form")
base_view = env.ref('stock.view_picking_form', raise_if_not_found=False)
if base_view:
    print(f"  id={base_view.id}, name={base_view.name}")
    print("  ---- RAW ARCH (arch_db) ----")
    print(base_view.arch_db)
else:
    print("  Không tìm thấy stock.view_picking_form")
