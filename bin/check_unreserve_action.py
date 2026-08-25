# -*- coding: utf-8 -*-
"""
check_unreserve_action.py
===================================
Đã override stock.picking.do_unreserve() (module website_public_inventory_18) để cảnh báo +
log + đồng bộ trạng thái stock.hold.request khi nút "Hủy dự trữ" (Unreserve) trong menu Actions
(⋮) của phiếu kho được bấm — nhưng test thực tế cho thấy KHÔNG có tác dụng gì (chatter không
có log mới, stock.hold.request vẫn giữ nguyên state='approved').

hasattr(stock.picking, 'do_unreserve') = True đã xác nhận method NÀY tồn tại, nhưng KHÔNG xác
nhận nút "Hủy dự trữ" thực sự gọi đúng method này — rất có thể (giống trường hợp nút "In phiếu
lấy hàng" hóa ra là do Odoo Studio tạo riêng, gọi 1 ir.actions.server/act_window khác) nút này
gọi 1 action hoàn toàn khác, không đi qua do_unreserve() nên override không bao giờ chạy.

Script này dò TẤT CẢ action (server action, window action, binding) có tên/code liên quan tới
"unreserve"/"dự trữ" gắn với model stock.picking hoặc stock.move.line, để biết chính xác cái gì
đang thực sự chạy.

CHỈ ĐỌC — không write/create/unlink gì.

Chạy bằng lệnh (trên Odoo.sh shell, hoặc odoo-bin shell tại môi trường đang chạy):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_unreserve_action.py
"""
import re

SEP = "=" * 90
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

section("1. ir.actions.server có tên hoặc code liên quan 'unreserve'/'dự trữ'/'Unreserve'")
servers = env['ir.actions.server'].sudo().search([
    '|', '|', '|',
    ('name', 'ilike', 'unreserve'),
    ('name', 'ilike', 'dự trữ'),
    ('code', 'ilike', 'unreserve'),
    ('model_id.model', 'in', ['stock.picking', 'stock.move', 'stock.move.line']),
])
for s in servers:
    xmlid = s.get_external_id().get(s.id) or '(không có external id)'
    print(f"  #{s.id:6d}  name={s.name!r:50s}  model={s.model_id.model if s.model_id else '?'}  state={s.state}  binding_model={s.binding_model_id.model if s.binding_model_id else ''}  xmlid={xmlid}")
    if s.state == 'code' and s.code:
        print("      ---- CODE ----")
        for line in s.code.splitlines():
            print("      " + line)

section("2. ir.actions.act_window có tên liên quan 'unreserve'/'dự trữ' cho stock.picking/stock.move.line")
windows = env['ir.actions.act_window'].sudo().search([
    ('res_model', 'in', ['stock.picking', 'stock.move', 'stock.move.line']),
])
for w in windows:
    if 'unreserve' in (w.name or '').lower() or 'dự trữ' in (w.name or '').lower():
        xmlid = w.get_external_id().get(w.id) or '(không có external id)'
        print(f"  #{w.id:6d}  name={w.name!r:50s}  res_model={w.res_model}  binding_model={w.binding_model_id.model if w.binding_model_id else ''}  xmlid={xmlid}")

section("3. Toàn bộ action có binding_model_id = stock.picking (mọi loại: server/window/report)")
bindings = env['ir.actions.actions'].sudo().search([('binding_model_id.model', '=', 'stock.picking')])
for b in bindings:
    print(f"  #{b.id:6d}  type={b.type:25s}  name={b.name!r:50s}  xmlid={b.get_external_id().get(b.id) or ''}")

section("4. Thử gọi trực tiếp do_unreserve() trên 1 phiếu giữ hàng cụ thể để xem override có chạy không")
# Tìm 1 phiếu giữ hàng đang approved bất kỳ để test AN TOÀN (không ảnh hưởng gì vì unreserve
# vốn không phá hủy dữ liệu, và ta có thể assign lại ngay sau nếu cần — nhưng để CHỈ ĐỌC, ta
# KHÔNG thực sự gọi ở đây, chỉ kiểm tra xem method có override đúng module không.
Picking = env['stock.picking']
method = Picking.do_unreserve
print(f"  do_unreserve function object: {method}")
print(f"  __module__: {getattr(method, '__module__', '?')}")
try:
    import inspect
    src_file = inspect.getsourcefile(method)
    print(f"  Định nghĩa (override cuối cùng theo MRO) nằm ở file: {src_file}")
except Exception as e:
    print(f"  Không lấy được source file: {e}")

section("5. Danh sách TẤT CẢ class kế thừa stock.picking có override do_unreserve (theo MRO)")
for cls in type(Picking).__mro__:
    if 'do_unreserve' in cls.__dict__:
        print(f"  - {cls.__module__}.{cls.__qualname__}")

section("XONG")
print("  Gửi lại toàn bộ output — đặc biệt mục 1 (server action code) và mục 5 (MRO) — để biết")
print("  chính xác cái gì đang chạy khi bấm 'Hủy dự trữ', và override của module mình có nằm")
print("  đúng vị trí trong chuỗi kế thừa hay không.")
