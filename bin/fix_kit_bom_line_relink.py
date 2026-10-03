# -*- coding: utf-8 -*-
"""
fix_kit_bom_line_relink.py
==========================
Gắn lại bom_line_id cho move linh kiện của dòng combo (kit/BoM phantom) đã mất liên kết, rồi cho
Odoo tính lại "Đã giao" của dòng đơn.

Nguyên nhân (soát bằng bin/check_kit_bom_line_lost_order.py / _all.py): wizard "Lấy SO từ MISA"
(misa_fetch_po_button/utils/misa_api_utils.py, _write_bom_from_children) xoá hết dòng BoM rồi tạo
lại → bom_line_id trên move cũ bị set NULL → sale_mrp không đếm được move nào → "Đã giao" 0 (case
DH125524949232179: giao đủ 2 bộ qua KBC/OUT/09403 mà đơn ghi 0).

Cách sửa, từng dòng kit:
  1. Lấy BoM kit hiện tại của sản phẩm; move chưa huỷ mà TRỐNG bom_line_id → gắn vào dòng BoM
     CÙNG SẢN PHẨM (cả move pick/pack/out và move trả — Odoo vốn để bom_line_id trên tất cả).
  2. Bỏ qua cả dòng nếu: có move đang trỏ dòng BoM của BoM KHÁC (Odoo sẽ chọn BoM đó, gắn lẫn
     hai BoM ra số sai), hoặc linh kiện của move không có / có >1 dòng trong BoM hiện tại.
  3. qty_delivered không depends bom_line_id nên phải tự đánh dấu tính lại. Tính xong phải BẰNG
     số thực giao suy theo linh kiện; lệch thì hoàn tác dòng đó (savepoint) và báo.

ORDERS: danh sách đơn cần sửa. Để [] = mọi dòng kit có move đã xong mà trống bom_line_id (đúng
tập ứng viên của bin/check_kit_bom_line_lost_all.py) — chỉ làm SAU KHI thử xong 1 đơn.

ONLY_WRONG = True (mặc định): chỉ dòng đang hiện sai. Log chỉ in dòng có Đã giao đổi / LỆCH / BỎ
QUA — dòng gắn lại mà số không đổi chỉ được đếm, để log không vượt giới hạn của shell.

DRY_RUN = True (mặc định): làm thật trong transaction để in Đã giao TRƯỚC → SAU, rồi rollback hết.
Đặt False để ghi (commit từng đơn).

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/fix_kit_bom_line_relink.py
"""

from collections import defaultdict

from odoo.addons.hlv_sale_delivery_planning.services.kit_qty_utils import kit_qty_from_components

ORDERS = []
# Chỉ sửa dòng ĐANG SAI (Đã giao lưu < thực giao). Dòng "sẽ sai" (lưu còn đúng, mất liên kết) để
# yên: đơn cũ đã qua mùa trả hàng nên gần như không còn gì kích Odoo tính lại chúng.
ONLY_WRONG = True
DRY_RUN = True
EPS = 0.001
SEP = "=" * 100

# Đúng bộ lọc sale_mrp dùng khi tính qty_delivered của kit (phía đơn bán nên in/out bị lật).
KIT_FILTERS = {
    'incoming_moves': lambda m: m._is_outgoing() and (not m.origin_returned_move_id or m.to_refund),
    'outgoing_moves': lambda m: m._is_incoming() and m.to_refund,
}
SaleLine = env['sale.order.line'].sudo()


class RelinkMismatch(Exception):
    """Tính lại xong không khớp số thực giao — để savepoint hoàn tác dòng đó."""


def kit_bom(line):
    return env['mrp.bom']._bom_find(line.product_id, company_id=line.company_id.id, bom_type='phantom')[line.product_id]


def real_kit_delivered(line, bom):
    """Số bộ thực giao RÒNG suy từ SL linh kiện theo SẢN PHẨM — không cần bom_line_id."""
    by_product = defaultdict(float)
    for move in line.move_ids.filtered(lambda m: m.state == 'done' and not m.scrapped):
        sign = 1 if KIT_FILTERS['incoming_moves'](move) else -1 if KIT_FILTERS['outgoing_moves'](move) else 0
        by_product[move.product_id.id] += sign * move.product_qty
    qty = kit_qty_from_components(bom, lambda product: by_product[product.id])
    return bom.product_uom_id._compute_quantity(qty, line.product_uom)


def relink_plan(line, bom):
    """{dòng BoM: move cần gắn} hoặc chuỗi lý do bỏ qua."""
    foreign = line.move_ids.filtered(lambda m: m.bom_line_id and m.bom_line_id not in bom.bom_line_ids)
    if foreign:
        return f"có move trỏ BoM khác ({', '.join(map(str, foreign.bom_line_id.bom_id.ids))})"
    bom_lines_by_product = defaultdict(lambda: env['mrp.bom.line'])
    for bom_line in bom.bom_line_ids:
        bom_lines_by_product[bom_line.product_id.id] |= bom_line
    plan = defaultdict(lambda: env['stock.move'])
    for move in line.move_ids.filtered(lambda m: m.state != 'cancel' and not m.bom_line_id):
        matches = bom_lines_by_product[move.product_id.id]
        if len(matches) != 1:
            product = move.product_id
            return (f"linh kiện {product.default_code or '(không mã)'} #{product.id} {product.name[:40]}"
                    f"{'' if product.active else ' [LƯU TRỮ]'} có {len(matches)} dòng trong BoM {bom.id}")
        plan[matches] |= move
    return plan


def recompute_delivered(line):
    env.add_to_compute(SaleLine._fields['qty_delivered'], line)
    line.flush_recordset(['qty_delivered'])
    return line.qty_delivered


def fix_line(line):
    """Gắn lại + tính lại 1 dòng kit; trả (trạng thái, ghi chú)."""
    bom = kit_bom(line)
    plan = relink_plan(line, bom)
    if isinstance(plan, str):
        return 'BỎ QUA', plan
    if not plan:
        return 'BỎ QUA', 'không có move nào trống bom_line_id'
    before, real = line.qty_delivered, real_kit_delivered(line, bom)
    try:
        with env.cr.savepoint():
            for bom_line, moves in plan.items():
                moves.write({'bom_line_id': bom_line.id})
            after = recompute_delivered(line)
            if abs(after - real) >= EPS:
                raise RelinkMismatch(after)
    except RelinkMismatch as mismatch:
        return 'LỆCH', f"tính lại ra {mismatch.args[0]:g} ≠ thực giao {real:g} — đã hoàn tác"
    moved = sum(len(m) for m in plan.values())
    return 'SỬA', f"gắn {moved} move vào BoM {bom.id} | Đã giao {before:g} → {after:g} (thực giao {real:g})"


if ORDERS:
    lines = SaleLine.search([('order_id.name', 'in', ORDERS), ('display_type', '=', False)])
else:
    env.cr.execute("""
        SELECT DISTINCT sm.sale_line_id
          FROM stock_move sm
          JOIN sale_order_line sol ON sol.id = sm.sale_line_id
         WHERE sm.state = 'done' AND sm.bom_line_id IS NULL AND sm.product_id <> sol.product_id
    """)
    lines = SaleLine.browse([r[0] for r in env.cr.fetchall()])
lines = lines.filtered(lambda l: l.state != 'cancel' and l.product_id and kit_bom(l))
if ONLY_WRONG:
    lines = lines.filtered(lambda l: real_kit_delivered(l, kit_bom(l)) - l.qty_delivered >= EPS)

print(f"\n{SEP}\n  GẮN LẠI bom_line_id — {'CHẠY THỬ (rollback cuối)' if DRY_RUN else 'GHI THẬT'}"
      f"{' — chỉ dòng ĐANG SAI' if ONLY_WRONG else ''}: {len(lines)} dòng kit / {len(lines.order_id)} đơn\n{SEP}")
counts = defaultdict(int)
for order in lines.order_id.sorted('date_order'):
    for line in lines.filtered(lambda l: l.order_id == order):
        before = line.qty_delivered
        status, note = fix_line(line)
        counts[status] += 1
        if status != 'SỬA' or abs(line.qty_delivered - before) >= EPS:
            print(f"  [{status:<7}] {order.name:<20} {line.product_id.default_code}: {note}")
    if not DRY_RUN:
        env.cr.commit()

if DRY_RUN:
    env.cr.rollback()
print(f"\n{SEP}\n  " + ' | '.join(f"{k}: {v}" for k, v in sorted(counts.items())))
print("  CHẠY THỬ — đã rollback, chưa ghi gì. Đặt DRY_RUN = False rồi chạy lại." if DRY_RUN else "  XONG — đã commit.")
print(SEP)
