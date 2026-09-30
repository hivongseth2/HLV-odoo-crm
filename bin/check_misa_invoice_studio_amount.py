# -*- coding: utf-8 -*-
"""
check_misa_invoice_studio_amount.py
===================================
Đánh giá TRƯỚC khi đổi cách tính "tiền xuất kho" của phiếu: hiện module lấy field Studio
x_studio_tng_tin_sau_thu (chụp 1 lần lúc xác nhận xuất kho). Case thật cho thấy số chụp đó có
thể SAI so với đơn bán hiện tại:
  - KBC/OUT/09162 + 09154: giao đủ 200 × 78.000 = 16.848.000 đ (HĐ cũng 16.848.000) mà 2 phiếu
    cộng lại chỉ ghi 13.068.000 đ.
  - KBC/OUT/11526: đơn và HĐ đều 47.671.200 đ, phiếu ghi 44.590.000 đ.
  - KBC/OUT/11613: combo — giá nằm ở dòng cha không giao, dòng con giá 0 → phiếu ghi 0 đ.

Cách tính đề xuất: tiền xuất kho = Σ số lượng từng move (quy về đơn vị của dòng đơn) × giá SAU
THUẾ hiện tại của dòng đơn bán gắn với move. Combo: dòng con giá 0 thì cộng phần giá dòng cha
theo tỉ lệ số lượng con đã giao.

Script so 2 cách cho mọi phiếu xuất kho đã xong trong phạm vi đối soát (không Shopee), in:
  - Tổng số phiếu lệch, tổng tiền lệch, chia theo lý do (combo / move không gắn dòng đơn /
    khác đơn vị tính / còn lại = giá đơn bán đổi sau khi xuất kho).
  - Với phiếu đã có HĐ: cách nào khớp HĐ (tiền HĐ quy về) hơn — để biết đổi cách tính có đúng.
  - Danh sách phiếu lệch lớn nhất.

CHỈ ĐỌC — không write/create/unlink gì, không gọi MISA.

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_misa_invoice_studio_amount.py
"""

from collections import defaultdict

STUDIO_FIELD = 'x_studio_tng_tin_sau_thu'
TOLERANCE = 1000.0      # đ
TOP = 40                # số phiếu lệch lớn nhất in ra
SALER_CODE = False      # False = mọi sale; hoặc 'TRANTHIMYDUYEN'

SEP = "=" * 100

Picking = env['stock.picking'].sudo()


def money(v):
    return f"{(v or 0.0):,.0f}".replace(",", ".")


def combo_parent_price(order, product):
    """Giá sau thuế / 1 SP con của dòng combo cha cùng đơn có BOM chứa product (0 nếu không có)."""
    for line in order.order_line.filtered(lambda l: l.price_total > 0 and l.product_id.bom_ids):
        bom_lines = line.product_id.bom_ids[:1].bom_line_ids
        own = bom_lines.filtered(lambda b: b.product_id == product)
        if not own:
            continue
        # Chia giá combo cho các SP con theo số lượng trong BOM (không có giá riêng từng con).
        total_units = sum(bom_lines.mapped('product_qty')) or 1.0
        per_combo = line.price_total / line.product_uom_qty if line.product_uom_qty else 0.0
        return per_combo / total_units
    return 0.0


def recomputed_amount(picking):
    """(tiền tính lại, set lý do) theo giá dòng đơn bán hiện tại."""
    amount = 0.0
    reasons = set()
    for move in picking.move_ids.filtered(lambda m: m.state == 'done'):
        line = move.sale_line_id
        if not line:
            reasons.add('move không gắn dòng đơn')
            continue
        qty = move.quantity
        if move.product_uom != line.product_uom:
            if move.product_uom.category_id == line.product_uom.category_id:
                qty = move.product_uom._compute_quantity(move.quantity, line.product_uom)
                reasons.add('khác đơn vị tính')
            else:
                # VD move "Cái" – dòng đơn "Bộ": Odoo không quy đổi được 2 nhóm đơn vị khác nhau,
                # giữ nguyên SL (coi 1 Cái = 1 Bộ) và đánh dấu riêng để xem tay.
                reasons.add(f'đơn vị khác nhóm ({move.product_uom.name}/{line.product_uom.name})')
        if line.price_total:
            amount += (line.price_total / line.product_uom_qty if line.product_uom_qty else 0.0) * qty
        else:
            parent_unit = combo_parent_price(line.order_id, move.product_id)
            if parent_unit:
                reasons.add('combo (dòng con giá 0)')
                amount += parent_unit * qty
    return amount, reasons


domain = Picking._misa_invoice_dashboard_base_domain()
if SALER_CODE:
    domain = domain + [('misa_invoice_saler_code', '=', SALER_CODE)]
pickings = Picking.search(domain)
print(f"\n{SEP}\n  SO TIỀN XUẤT KHO: field Studio vs tính lại theo giá đơn bán hiện tại — {len(pickings)} phiếu\n{SEP}")

rows = []
by_reason = defaultdict(lambda: {'count': 0, 'diff': 0.0})
better = {'studio': 0, 'recomputed': 0, 'same': 0}
for picking in pickings:
    studio = getattr(picking, STUDIO_FIELD, 0.0) or 0.0
    new, reasons = recomputed_amount(picking)
    diff = new - studio
    if abs(diff) <= TOLERANCE:
        continue
    reason = ', '.join(sorted(reasons)) or 'giá đơn bán đổi sau khi xuất kho'
    by_reason[reason]['count'] += 1
    by_reason[reason]['diff'] += diff
    allocated = picking.misa_invoice_allocated_amount or 0.0
    verdict = ''
    if picking.misa_invoice_state == 'invoiced' and allocated:
        old_gap = abs(studio - (picking.misa_invoice_returned_amount or 0.0) - allocated)
        new_gap = abs(new - (picking.misa_invoice_returned_amount or 0.0) - allocated)
        if new_gap + TOLERANCE < old_gap:
            better['recomputed'] += 1
            verdict = 'tính lại KHỚP HĐ hơn'
        elif old_gap + TOLERANCE < new_gap:
            better['studio'] += 1
            verdict = '⚠️ Studio khớp HĐ hơn'
        else:
            better['same'] += 1
    rows.append((picking, studio, new, diff, reason, verdict))

print(f"\n  {len(rows)} phiếu lệch > {money(TOLERANCE)} đ, tổng chênh (tính lại − Studio): {money(sum(r[3] for r in rows))} đ")
print("\n  Theo lý do:")
for reason, info in sorted(by_reason.items(), key=lambda kv: -abs(kv[1]['diff'])):
    print(f"    {reason:<45} {info['count']:>5} phiếu   {money(info['diff']):>16} đ")
print("\n  Phiếu đã có HĐ — cách nào khớp tiền HĐ hơn:")
print(f"    tính lại khớp hơn: {better['recomputed']}   Studio khớp hơn: {better['studio']}   như nhau: {better['same']}")

print(f"\n  {TOP} phiếu lệch lớn nhất:")
for picking, studio, new, diff, reason, verdict in sorted(rows, key=lambda r: -abs(r[3]))[:TOP]:
    print(f"    {picking.name:<16} {str(picking.date_done)[:10]} {', '.join(picking.misa_invoice_sale_order_ids.mapped('name')):<20}"
          f" Studio {money(studio):>13} → tính lại {money(new):>13} ({money(diff):>12})"
          f" HĐ quy về {money(picking.misa_invoice_allocated_amount):>13} | {reason}{' | ' + verdict if verdict else ''}")
print(f"\n{SEP}")
print("  Đọc kết quả: 'tính lại khớp HĐ hơn' áp đảo 'Studio khớp hơn' → đổi sang tính theo giá đơn bán\n"
      "  là đúng. Nhiều 'Studio khớp hơn' → đơn bán bị sửa giá SAU khi xuất HĐ, cần xem lại trước khi đổi.")
print(SEP)
