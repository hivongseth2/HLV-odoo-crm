# -*- coding: utf-8 -*-
"""
fix_misa_invoice_picking_amount_from_so.py
==========================================
Sửa tay tiền thực xuất (misa_invoice_net_actual_amount) cho SỐ ÍT phiếu mà field Studio
x_studio_tng_tin_sau_thu (chụp lúc xác nhận xuất kho) ghi sai, tính lại theo đơn bán hiện tại.

Đánh giá đã chạy (check trên 6.159 phiếu): Studio khớp HĐ ở 307 phiếu, tính lại chỉ khớp hơn ở 22
— nên KHÔNG đổi cách tính chung, chỉ sửa đúng những phiếu:
  1. "Sạch": mọi move gắn dòng đơn bán, CÙNG đơn vị tính (hoặc quy đổi được) với dòng đơn — phiếu
     có đơn vị khác nhóm (Cái/Bộ...) tính lại sai, Studio lại đúng, bỏ qua hẳn.
  2. Thuộc 1 đơn duy nhất, và ở MỨC ĐƠN HÀNG tổng tính lại KHỚP ĐÚNG tiền HĐ (trong TOLERANCE)
     còn Studio thì không (1 đơn giao nhiều phiếu, HĐ rót theo thứ tự xuất nên so từng phiếu
     riêng dễ sai). Đơn chưa có HĐ không bao giờ bị sửa.
  3. Chỉ hàng thường: phiếu có move kit hoặc move gắn dòng đơn giá 0 (combo tách dòng, hàng tặng)
     bỏ qua hẳn — các phiếu đó đã tính đúng bằng công thức Studio mới (xem
     bin/recompute_studio_amount_kit_combo.py); tính lại kiểu SL × giá dòng ở đây sai với kit.
Case thật: KBC/OUT/09154+09162 (giá đơn đổi sau khi xuất: 13.068.000 → 16.848.000 đ), KBC/OUT/11526
(44.590.000 → 47.671.200 đ).

Tính lại = Σ SL move (quy về đơn vị dòng đơn) × giá SAU THUẾ hiện tại của dòng đơn. Trừ hàng đã
trả (misa_invoice_returned_amount) như cách module vẫn tính.

Lưu ý: chỉ ghi field của module đối soát, KHÔNG ghi field Studio. Phiếu có hàng trả về sau,
_misa_invoice_recompute_net_amount tính lại từ Studio và số sửa tay mất — chạy lại script này.

DRY_RUN = True (mặc định): chỉ in sẽ sửa gì. Đặt False để ghi thật (script tự commit).

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/fix_misa_invoice_picking_amount_from_so.py
"""

from collections import defaultdict

DRY_RUN = True
SALER_CODE = False      # False = mọi sale
ONLY_PICKINGS = []      # để trống = soát hết; hoặc ['KBC/OUT/11526', ...]
TOLERANCE = 1000.0      # đ

STUDIO_FIELD = 'x_studio_tng_tin_sau_thu'
SEP = "=" * 100

Picking = env['stock.picking'].sudo()


def money(v):
    return f"{(v or 0.0):,.0f}".replace(",", ".")


def recompute(picking):
    """(tiền tính lại chưa trừ hàng trả, sạch?). Không sạch khi có move không gắn dòng đơn, đơn vị
    khác nhóm, hoặc thuộc nhánh kit / dòng giá 0 của công thức Studio (cùng điều kiện với
    touches_new_branches trong bin/recompute_studio_amount_kit_combo.py) — không tính lại ở đây."""
    amount, clean = 0.0, True
    for move in picking.move_ids.filtered(lambda m: m.state == 'done'):
        line = move.sale_line_id
        if not line or move.bom_line_id or move.product_id != line.product_id or not line.price_total:
            clean = False
            continue
        qty = move.quantity
        if move.product_uom != line.product_uom:
            if move.product_uom.category_id != line.product_uom.category_id:
                clean = False
                continue
            qty = move.product_uom._compute_quantity(move.quantity, line.product_uom)
        amount += (line.price_total / line.product_uom_qty if line.product_uom_qty else 0.0) * qty
    return amount, clean


domain = Picking._misa_invoice_dashboard_base_domain()
if SALER_CODE:
    domain += [('misa_invoice_saler_code', '=', SALER_CODE)]
if ONLY_PICKINGS:
    domain += [('name', 'in', ONLY_PICKINGS)]

# Gom theo đơn: chỉ xét phiếu 1 đơn, tính lại được và lệch Studio.
candidates = defaultdict(list)
for picking in Picking.search(domain):
    orders = picking.misa_invoice_sale_order_ids
    if len(orders) != 1:
        continue
    amount, clean = recompute(picking)
    studio = getattr(picking, STUDIO_FIELD, 0.0) or 0.0
    if clean and abs(amount - studio) > TOLERANCE:
        candidates[orders.id].append((picking, studio, amount))

print(f"\n{SEP}\n  SỬA TIỀN THỰC XUẤT THEO ĐƠN BÁN — {'CHẠY THỬ' if DRY_RUN else 'GHI THẬT'}\n{SEP}")
fixed = skipped = 0
for order_id, items in candidates.items():
    order = env['sale.order'].sudo().browse(order_id)
    fix_ids = {p.id for p, *_ in items}
    order_pickings = order.misa_invoice_picking_ids.filtered(lambda p: p.state == 'done' and p.picking_type_id.code == 'outgoing')
    new_by_id = {p.id: amount for p, _studio, amount in items}
    returned = {p.id: p.misa_invoice_returned_amount or 0.0 for p in order_pickings}
    allocated = sum(order_pickings.mapped('misa_invoice_allocated_amount'))
    old_total = sum(order_pickings.mapped('misa_invoice_net_actual_amount'))
    new_total = sum(
        (new_by_id[p.id] - returned[p.id]) if p.id in fix_ids else (p.misa_invoice_net_actual_amount or 0.0)
        for p in order_pickings
    )
    # Chỉ sửa khi tính lại KHỚP ĐÚNG tiền HĐ của đơn còn Studio thì không — "gần hơn" là chưa đủ:
    # đơn chưa có HĐ (0 đ) thì số nào nhỏ hơn cũng "gần hơn", sẽ kéo tiền xuất kho xuống sai.
    better = allocated > TOLERANCE and abs(new_total - allocated) <= TOLERANCE < abs(old_total - allocated)
    label = '✅ SỬA' if better else '⏭ bỏ qua (tính lại không khớp đúng HĐ)'
    print(f"\n  {label}  đơn {order.name} — HĐ quy về {money(allocated)} | XK hiện {money(old_total)} → tính lại {money(new_total)}")
    for picking, studio, amount in items:
        print(f"      {picking.name:<16} Studio {money(studio):>13} → {money(amount - returned[picking.id]):>13}")
    if not better:
        skipped += 1
        continue
    fixed += 1
    if DRY_RUN:
        continue
    for picking, studio, amount in items:
        new_net = max(amount - returned[picking.id], 0.0)
        picking.write({'misa_invoice_net_actual_amount': new_net})
        picking.message_post(body=(
            "Sửa tay tiền thực xuất %s → %s đ theo giá đơn bán hiện tại (bin/fix_misa_invoice_picking_amount_from_so.py): "
            "field Studio chụp lúc xuất kho ghi %s đ."
        ) % (money(studio - returned[picking.id]), money(new_net), money(studio)))
    order.filtered('misa_invoice_order_checked_at')._misa_invoice_apply_order_allocation()

print(f"\n{SEP}\n  {fixed} đơn sửa, {skipped} đơn bỏ qua.")
if DRY_RUN:
    print("  CHẠY THỬ — chưa ghi gì. Đặt DRY_RUN = False rồi chạy lại.")
else:
    env.cr.commit()
    print("  ĐÃ GHI + COMMIT.")
print(SEP)
