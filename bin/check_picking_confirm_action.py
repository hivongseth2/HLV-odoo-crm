# -*- coding: utf-8 -*-
"""
check_picking_confirm_action.py
===============================
Menu Tác vụ của phiếu kho (list) đang hiện "Xác nhận" chứ không thấy "Xác nhận (An toàn)".

- "Xác nhận" = stock.action_validate_picking (core, msgid "Validate" dịch vi là "Xác nhận"),
  gọi thẳng button_validate() — KHÔNG chặn phiếu PACK.
- "Xác nhận (An toàn)" = custom_picking_confirm.action_server_confirm_safe, chặn phiếu PACK
  (trừ phiếu trả). Trong code không module nào ẩn nó; axenor_print_action_hide chỉ lọc menu In
  (ir.actions.report), không đụng server action.

Vậy nếu nó không hiện thì chỉ có thể do dữ liệu: module chưa cài, action bị xoá, hoặc ai đó bấm
"Gỡ tác vụ theo ngữ cảnh" (binding_model_id = False), hoặc bị gắn groups. Script soát các khả năng đó.

CHỈ ĐỌC.
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_picking_confirm_action.py
"""

SEP = "=" * 90
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

section("1. Module custom_picking_confirm")
mod = env['ir.module.module'].sudo().search([('name', '=', 'custom_picking_confirm')])
print(f"  state = {mod.state if mod else '(không có trong danh sách module)'}")

section("2. Action 'Xác nhận (An toàn)' và action core 'Validate'")
for xmlid in ('custom_picking_confirm.action_server_confirm_safe', 'stock.action_validate_picking'):
    act = env.ref(xmlid, raise_if_not_found=False)
    if not act:
        print(f"  {xmlid}: KHÔNG TỒN TẠI")
        continue
    act = act.sudo()
    print(f"  {xmlid}: #{act.id} name={act.name!r} binding_model={act.binding_model_id.model or '(đã gỡ)'}"
          f" view_types={act.binding_view_types!r} groups={act.groups_id.mapped('full_name') or '-'}")

section("3. Mọi server action gắn vào stock.picking có tên chứa 'xác nhận' / 'validate' / 'confirm'")
acts = env['ir.actions.server'].sudo().with_context(active_test=False).search([
    ('model_id.model', '=', 'stock.picking'),
    '|', '|', ('name', 'ilike', 'xác nhận'), ('name', 'ilike', 'validate'), ('name', 'ilike', 'confirm'),
])
for a in acts:
    print(f"  #{a.id:6d} name={a.name!r:35s} binding={a.binding_model_id.model or '-':15s}"
          f" groups={a.groups_id.mapped('full_name') or '-'} xmlid={a.get_external_id().get(a.id) or ''}")

section("4. Lịch sử: ai sửa action An toàn lần cuối")
act = env.ref('custom_picking_confirm.action_server_confirm_safe', raise_if_not_found=False)
if act:
    act = act.sudo()
    print(f"  write_uid={act.write_uid.name} write_date={act.write_date}")

env.cr.rollback()
section("XONG — gửi lại toàn bộ output")
