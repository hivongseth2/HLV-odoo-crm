# -*- coding: utf-8 -*-
"""
fix_kit_unexploded_move.py
==========================
Combo (kit/BoM phantom) bị kẹt vì phiếu kho đang xuất CHÍNH mã combo thay vì linh kiện.

Case thật DH125524949234781: đơn xác nhận 31/07 khi combo CB-M18ONEFHIWF1-2.M18FB8-M12-18FC CHƯA có
BoM → Odoo tạo move xuất đúng mã combo (KBC/PICK/10754, "confirmed"). Combo không bao giờ có tồn nên
phiếu chờ hàng mãi. 21/08 BoM 1209 mới được tạo, nhưng Odoo không tự nổ lại move đã có.

Bẫy nếu để nguyên: khi đã có BoM, sale_mrp._get_qty_procurement chỉ đếm move LINH KIỆN có
bom_line_id → move mã combo tính 0 → lần tới có gì gọi _action_launch_stock_rule (sửa SL dòng, đồng
bộ lại đơn) Odoo sẽ tạo THÊM move linh kiện mà move mã combo vẫn treo → xuất trùng.

Cách sửa, từng dòng kit:
  1. Huỷ mọi move CHƯA XONG của chính mã combo trên dòng (cả chuỗi pick/pack/out nếu có).
  2. Gọi lại _action_launch_stock_rule → Odoo nổ BoM hiện tại ra move linh kiện (gắn bom_line_id),
     tự xếp vào phiếu đang mở cùng nhóm hoặc tạo phiếu mới.
  3. Kiểm: số bộ đã "đặt kho" (_get_qty_procurement) phải = SL đặt; lệch / lỗi thì hoàn tác (savepoint).
Bỏ qua (cần người xem) nếu: đơn bị khoá; đơn có dòng con giá 0 chứa linh kiện (combo đã "xổ" trên
đơn — nổ BoM nữa là giao trùng, xem bin/check_kit_children_lines.py); mã combo đã có move XONG (đã xuất chính mã combo — tồn kho
combo đã bị trừ, phải xử lý tay); move mã combo đang giữ hàng hoặc đã đánh dấu lấy.

ORDERS: đơn cần sửa. Để [] = quét mọi dòng kit đang có move chưa xong của chính mã combo.

DRY_RUN = True (mặc định): làm thật trong transaction để in kết quả, rồi rollback hết. Đặt False để ghi
(commit từng đơn).

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/fix_kit_unexploded_move.py
"""

from collections import defaultdict

ORDERS = ['DH125524949234781']
DRY_RUN = True
EPS = 0.001
SEP = "=" * 100

SaleLine = env['sale.order.line'].sudo()
Move = env['stock.move'].sudo()


class ExplodeMismatch(Exception):
    """Nổ lại xong mà số bộ đặt kho ≠ SL đặt — để savepoint hoàn tác dòng đó."""


def kit_bom(line):
    return env['mrp.bom']._bom_find(line.product_id, company_id=line.company_id.id, bom_type='phantom')[line.product_id]


def combo_moves(line):
    """Move chưa xong của CHÍNH mã combo trên dòng, kèm các bước sau/trước trong chuỗi."""
    moves = line.move_ids.filtered(lambda m: m.product_id == line.product_id and m.state not in ('done', 'cancel'))
    seen = Move.browse()
    while moves:
        seen |= moves
        moves = (moves.move_orig_ids | moves.move_dest_ids).filtered(
            lambda m: m.product_id == line.product_id and m.state not in ('done', 'cancel')) - seen
    return seen


def has_children_lines(line):
    """Đơn có dòng con thành tiền 0 là linh kiện của combo = combo đã "xổ" trên đơn (trước cf9dda1fe)."""
    components = kit_bom(line).bom_line_ids.product_id
    return bool((line.order_id.order_line - line).filtered(
        lambda l: not l.display_type and abs(l.price_subtotal) < EPS and l.product_id in components))


def skip_reason(line, moves):
    if line.order_id.locked:
        return "đơn đang bị khoá"
    if has_children_lines(line):
        # Linh kiện đã đi qua dòng con — nổ BoM cho dòng combo nữa là kho giao TRÙNG.
        return "đơn có dòng con giá 0 đã chứa linh kiện (xem bin/check_kit_children_lines.py) — KHÔNG nổ lại"
    if line.move_ids.filtered(lambda m: m.product_id == line.product_id and m.state == 'done'):
        return "mã combo đã có move XONG (đã xuất chính mã combo) — xử lý tay"
    if moves.filtered(lambda m: m.quantity > 0 or m.picked):
        return "move mã combo đang giữ hàng / đã đánh dấu lấy — xử lý tay"
    return ''


def picking_names(moves):
    return ', '.join(f"{p.name} ({p.state})" for p in moves.picking_id.sorted('id')) or '-'


def fix_line(line):
    """Huỷ move mã combo + nổ lại BoM cho 1 dòng; trả (trạng thái, ghi chú)."""
    moves = combo_moves(line)
    if not moves:
        return 'BỎ QUA', 'không có move chưa xong của chính mã combo'
    reason = skip_reason(line, moves)
    if reason:
        return 'BỎ QUA', f"{reason} | {picking_names(moves)}"
    old_pickings, before_ids = picking_names(moves), set(line.move_ids.ids)
    pr_note = ''
    if 'created_purchase_request_line_id' in Move._fields and moves.created_purchase_request_line_id:
        pr_note = f" | ⚠️ có yêu cầu mua cho mã combo: {', '.join(moves.created_purchase_request_line_id.request_id.mapped('name'))}"
    try:
        with env.cr.savepoint():
            moves._action_cancel()
            line._action_launch_stock_rule()
            procured = line._get_qty_procurement()
            if abs(procured - line.product_uom_qty) >= EPS:
                raise ExplodeMismatch(f"đặt kho {procured:g} bộ ≠ đặt {line.product_uom_qty:g}")
    except Exception as error:  # noqa: BLE001 — lỗi gì cũng hoàn tác dòng này, báo ra rồi đi tiếp
        return 'LỖI', f"{error} — đã hoàn tác"
    new_moves = line.move_ids.filtered(lambda m: m.id not in before_ids and m.state != 'cancel')
    parts = ', '.join(f"{m.product_id.default_code} x{m.product_uom_qty:g}" for m in new_moves.sorted('id'))
    return 'SỬA', (f"huỷ {len(moves)} move mã combo [{old_pickings}] → {len(new_moves)} move linh kiện "
                   f"[{parts}] vào {picking_names(new_moves)}{pr_note}")


if ORDERS:
    lines = SaleLine.search([('order_id.name', 'in', ORDERS), ('display_type', '=', False)])
else:
    env.cr.execute("""
        SELECT DISTINCT sm.sale_line_id
          FROM stock_move sm
          JOIN sale_order_line sol ON sol.id = sm.sale_line_id
         WHERE sm.state NOT IN ('done', 'cancel') AND sm.product_id = sol.product_id
    """)
    lines = SaleLine.browse([r[0] for r in env.cr.fetchall()])
lines = lines.filtered(lambda l: l.state == 'sale' and l.product_id and kit_bom(l) and combo_moves(l))

print(f"\n{SEP}\n  NỔ LẠI BoM CHO COMBO KẸT — {'CHẠY THỬ (rollback cuối)' if DRY_RUN else 'GHI THẬT'}: "
      f"{len(lines)} dòng kit / {len(lines.order_id)} đơn\n{SEP}")
counts = defaultdict(int)
for order in lines.order_id.sorted('date_order'):
    for line in lines.filtered(lambda l: l.order_id == order):
        status, note = fix_line(line)
        counts[status] += 1
        print(f"  [{status:<7}] {order.name:<20} {line.product_id.default_code}: {note}")
    if not DRY_RUN:
        env.cr.commit()

if DRY_RUN:
    env.cr.rollback()
print(f"\n{SEP}\n  " + (' | '.join(f"{k}: {v}" for k, v in sorted(counts.items())) or 'Không có dòng nào'))
print("  CHẠY THỬ — đã rollback, chưa ghi gì. Đặt DRY_RUN = False rồi chạy lại." if DRY_RUN else "  XONG — đã commit.")
print(SEP)
