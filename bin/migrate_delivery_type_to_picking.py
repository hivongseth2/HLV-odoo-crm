# -*- coding: utf-8 -*-
"""
migrate_delivery_type_to_picking.py
========================================
Trước đây tính năng "bắt buộc chọn Hình thức giao hàng trước khi in phiếu lấy hàng" (trên
/sale_plan) dùng field cấp ĐƠN HÀNG (sale.order.x_studio_delivery_type, field Odoo Studio) —
đã đổi sang field cấp PHIẾU (stock.picking.x_pick_delivery_type, field mới của module này), vì
1 đơn có thể có NHIỀU lần lấy hàng (backorder), mỗi lần có thể giao theo hình thức khác nhau,
không nên dùng chung 1 giá trị cho cả đơn nữa.

Script này BACKFILL 1 LẦN cho dữ liệu cũ: với mỗi sale.order đã có x_studio_delivery_type,
copy giá trị đó xuống TẤT CẢ phiếu (stock.picking) của đơn CHƯA có x_pick_delivery_type — để
các phiếu PICK đang chờ xử lý không đột ngột bị chặn in vì "chưa có Hình thức giao hàng" ngay
sau khi module upgrade (trước đó đơn đã có giá trị rồi, chỉ là chưa nằm ở field mới).

⚠️ SCRIPT NÀY CÓ GHI DỮ LIỆU (không phải chỉ đọc) — nhưng chỉ ghi vào field MỚI
(x_pick_delivery_type), KHÔNG đụng/xóa gì field cũ (x_studio_delivery_type) hay bất kỳ dữ liệu
nào khác. Chỉ ghi cho phiếu đang CHƯA có giá trị (an toàn chạy lại nhiều lần — idempotent).

Chạy bằng lệnh (trên Odoo.sh shell):
    python odoo-bin shell -d <TEN_DATABASE> < bin/migrate_delivery_type_to_picking.py
"""

SEP = "=" * 100
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

section("Tìm đơn hàng có x_studio_delivery_type nhưng còn phiếu chưa có x_pick_delivery_type")

SaleOrder = env['sale.order'].sudo()
orders = SaleOrder.search([('x_studio_delivery_type', '!=', False)])
print(f"  Tổng số đơn có x_studio_delivery_type: {len(orders)}")

updated_pickings = 0
updated_orders = 0
skipped_no_picking = 0

for so in orders:
    pickings_to_update = so.picking_ids.filtered(lambda p: not p.x_pick_delivery_type)
    if not pickings_to_update:
        continue
    pickings_to_update.write({'x_pick_delivery_type': so.x_studio_delivery_type})
    updated_pickings += len(pickings_to_update)
    updated_orders += 1

env.cr.commit()

section("KẾT QUẢ")
print(f"  Số đơn đã xử lý (có ít nhất 1 phiếu được cập nhật): {updated_orders}")
print(f"  Tổng số phiếu (stock.picking) đã được set x_pick_delivery_type: {updated_pickings}")
print("  Đã commit. Field cũ sale.order.x_studio_delivery_type GIỮ NGUYÊN, không bị xóa/đổi.")
