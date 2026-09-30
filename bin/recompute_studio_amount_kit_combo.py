# -*- coding: utf-8 -*-
"""
recompute_studio_amount_kit_combo.py
====================================
Sau khi dán công thức mới vào field Studio x_studio_tng_tin_sau_thu (đã chạy thử bằng
bin/check_studio_amount_new_formula.py): tính lại field đó CHỈ cho phiếu xuất kho trong phạm vi
đối soát có kit / combo tách dòng / hàng giá 0 — đúng các nhánh công thức mới sửa. Phiếu hàng
thường giữ nguyên số đã chụp lúc xuất kho (lần chạy thử: tính lại theo giá hiện tại khớp HĐ
ngang ngửa số cũ 31/31, nên không đụng).

Lưu công thức trong Settings/Studio KHÔNG tự tính lại phiếu cũ (Odoo chỉ tính lại cả bảng khi
field là cột mới) — nên phải chạy script này.

Phiếu nào đổi số thì tính lại luôn tiền hàng trả + tiền thực xuất ròng và chia lại tiền HĐ của
đơn (_misa_invoice_recompute_net_amount) — thuần DB, không gọi MISA. Tiền thực xuất sửa tay
bằng bin/fix_misa_invoice_picking_amount_from_so.py trên các phiếu này sẽ bị thay bằng số tính
từ field Studio mới (VD KBC/OUT/11613 — công thức mới ra đúng số đó).

DRY_RUN = True (mặc định): tính thử rồi rollback, chỉ in sẽ đổi gì. Đặt False để ghi thật
(commit sau mỗi lô).

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/recompute_studio_amount_kit_combo.py
"""

DRY_RUN = True
ONLY_PICKINGS = []      # để trống = mọi phiếu trong phạm vi; hoặc ['KBC/OUT/11613', ...]
# Phiếu KHÔNG tính lại: KBC/OUT/09744 — số cũ khớp đúng HĐ, công thức mới chỉ lệch +2.960 đ do giá
# dòng kit bị làm tròn lại sau khi xuất; tính lại sẽ đẻ ra khoản lệch 2.960 đ trên đơn đã khớp.
SKIP_PICKINGS = ['KBC/OUT/09744']
TOLERANCE = 1000.0      # đ — chỉ in phiếu đổi quá mức này
BATCH = 300
STUDIO_FIELD = 'x_studio_tng_tin_sau_thu'
# Chuỗi chỉ có trong công thức mới — chặn chạy khi chưa dán (tính lại bằng công thức cũ là vô ích).
NEW_FORMULA_MARKER = 'own_value'
SEP = "=" * 100

Picking = env['stock.picking'].sudo()


def money(v):
    return f"{(v or 0.0):,.0f}".replace(",", ".")


def touches_new_branches(picking):
    """Phiếu có move kit (linh kiện của dòng kit) hoặc move gắn dòng đơn giá 0 (combo tách dòng /
    hàng tặng) — các nhánh công thức mới đổi cách tính."""
    for move in picking.move_ids_without_package:
        line = move.sale_line_id
        if line and (move.bom_line_id or move.product_id != line.product_id or line.price_total == 0):
            return True
    return False


studio_code = env['ir.model.fields'].sudo()._get('stock.picking', STUDIO_FIELD).compute or ''
if NEW_FORMULA_MARKER not in studio_code:
    raise SystemExit(f"❌ Field {STUDIO_FIELD} vẫn là công thức cũ — dán công thức mới vào trước rồi chạy lại.")

field = Picking._fields[STUDIO_FIELD]
domain = Picking._misa_invoice_dashboard_base_domain()
if ONLY_PICKINGS:
    domain += [('name', 'in', ONLY_PICKINGS)]
if SKIP_PICKINGS:
    domain += [('name', 'not in', SKIP_PICKINGS)]
picking_ids = Picking.search(domain).ids

print(f"\n{SEP}\n  TÍNH LẠI {STUDIO_FIELD} CHO PHIẾU KIT / COMBO / GIÁ 0 — {'CHẠY THỬ' if DRY_RUN else 'GHI THẬT'}"
      f" ({len(picking_ids)} phiếu trong phạm vi)\n{SEP}")
targeted = changed = 0
for start in range(0, len(picking_ids), BATCH):
    batch = Picking.browse(picking_ids[start:start + BATCH]).filtered(touches_new_branches)
    targeted += len(batch)
    if not batch:
        continue
    before = {p.id: (getattr(p, STUDIO_FIELD) or 0.0, p.misa_invoice_net_actual_amount or 0.0) for p in batch}
    env.add_to_compute(field, batch)
    batch.flush_recordset([STUDIO_FIELD])
    for picking in batch:
        old, old_net = before[picking.id]
        new = getattr(picking, STUDIO_FIELD) or 0.0
        if abs(new - old) <= TOLERANCE:
            continue
        changed += 1
        if DRY_RUN:
            new_net = max(new - picking._misa_invoice_returned_amount_for(new), 0.0)
        else:
            picking._misa_invoice_recompute_net_amount()
            new_net = picking.misa_invoice_net_actual_amount or 0.0
            picking.message_post(body=(
                "Tính lại tiền hàng %s → %s đ theo công thức Studio mới (kit/combo chia theo phần đã giao, "
                "hàng tặng 0 đ) — bin/recompute_studio_amount_kit_combo.py."
            ) % (money(old), money(new)))
        orders = ', '.join(picking.misa_invoice_sale_order_ids.mapped('name'))
        print(f"  {picking.name:<16} {orders:<20} tiền hàng {money(old):>13} → {money(new):>13}"
              f" | thực xuất {money(old_net):>13} → {money(new_net):>13}")
    if DRY_RUN:
        env.cr.rollback()
    else:
        env.cr.commit()
    env.invalidate_all(flush=False)

print(f"\n{SEP}\n  {targeted} phiếu kit/combo/giá 0 được tính lại, {changed} phiếu đổi > {money(TOLERANCE)} đ.")
print("  CHẠY THỬ — đã rollback, chưa ghi gì. Đặt DRY_RUN = False rồi chạy lại." if DRY_RUN else "  ĐÃ GHI + COMMIT.")
print(SEP)
