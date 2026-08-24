# -*- coding: utf-8 -*-
"""
check_stock_quant_editable_view.py
===================================
Đang thêm cột "Đã giữ (Giữ hàng theo Sale)" vào màn "Cập nhật số lượng" (mở từ nút On
Hand/Vị trí trên sản phẩm, model stock.quant). View kế thừa xpath //field[@name='quantity']
bị lỗi "cannot be located in parent view" — Odoo báo view cha là id=812. Script này đọc
thẳng arch THẬT của view id=812 (và toàn bộ view khác của stock.quant + action liên quan)
để biết chính xác field nào đại diện cho "Số lượng hiện tại", tránh đoán mò lần nữa.

CHỈ ĐỌC — không write/create/unlink gì.

Chạy bằng lệnh (trên Odoo.sh shell, hoặc odoo-bin shell tại môi trường đang chạy):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_stock_quant_editable_view.py
"""

SEP = "=" * 90
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

section("1. Thử các external id nghi ngờ cho view editable của stock.quant")
xmlids_to_try = [
    "stock.view_stock_quant_tree_editable",
    "stock.view_stock_quant_tree",
    "stock.view_stock_quant_form_editable",
    "stock.quant_search_view",
    "stock.view_stock_quant_form",
]
for xmlid in xmlids_to_try:
    rec = env.ref(xmlid, raise_if_not_found=False)
    if rec:
        print(f"  OK  {xmlid:45s} -> id={rec.id}, type={rec.type}, model={rec.model}")
    else:
        print(f"  --  {xmlid:45s}: KHÔNG tồn tại")

section("2. Liệt kê TẤT CẢ view của model stock.quant")
views = env['ir.ui.view'].sudo().search([('model', '=', 'stock.quant')], order='id')
for v in views:
    xmlid = v.get_external_id().get(v.id) or '(không có external id)'
    inherit = v.inherit_id.id if v.inherit_id else ''
    print(f"  #{v.id:6d}  type={v.type:8s}  name={v.name:50s}  inherit_id={inherit!s:6s}  xmlid={xmlid}")

section("3. Action mở stock.quant (On Hand / Update Quantity)")
actions = env['ir.actions.act_window'].sudo().search([('res_model', '=', 'stock.quant')])
for a in actions:
    xmlid = a.get_external_id().get(a.id) or '(không có external id)'
    print(f"  #{a.id:6d}  name={a.name:45s}  view_mode={a.view_mode:25s}  view_id={a.view_id.id if a.view_id else ''}  xmlid={xmlid}")
    for vv in a.view_ids:
        print(f"        - view_mode={vv.view_mode}, view_id={vv.view_id.id if vv.view_id else '(default)'}")

section("4. ARCH GỐC (raw, chưa compose qua inherit) của view id=812 — parent view báo lỗi")
v812 = env['ir.ui.view'].sudo().browse(812)
if v812.exists():
    xmlid812 = v812.get_external_id().get(812) or '(không có external id)'
    print(f"  Tên: {v812.name}")
    print(f"  Model: {v812.model}")
    print(f"  Type: {v812.type}")
    print(f"  Xmlid: {xmlid812}")
    print(f"  Inherit_id: {v812.inherit_id.id if v812.inherit_id else '(không có, đây là view gốc)'}")
    print("  ---- RAW ARCH (arch_db) ----")
    print(v812.arch_db)
else:
    print("  Không tìm thấy view id=812 (lạ — vì error message vừa báo đúng id này)")

section("5. ARCH ĐÃ COMPOSE (qua get_view) — đúng cái Odoo thực sự render ra màn hình")
Quant = env['stock.quant']
for vt in ('list', 'tree'):
    try:
        res = Quant.get_view(view_id=812, view_type=vt)
        print(f"  ---- COMPOSED ARCH (view_type={vt}) ----")
        print(res.get('arch'))
        break
    except Exception as e:
        print(f"  get_view(view_id=812, view_type={vt}) lỗi: {e}")

section("6. Tìm mọi field liên quan đến 'số lượng' trong arch gốc view 812 (regex thô)")
import re
if v812.exists():
    field_names = sorted(set(re.findall(r'field name="([^"]+)"', v812.arch_db or '')))
    print("  Tất cả field xuất hiện trong arch:")
    for fn in field_names:
        print(f"    - {fn}")

section("XONG")
print("  Gửi lại toàn bộ output này (đặc biệt mục 4 và 5) để xác định đúng field 'Số lượng hiện")
print("  tại' cần neo xpath vào (thay vì 'quantity'), trước khi sửa lại view kế thừa.")
