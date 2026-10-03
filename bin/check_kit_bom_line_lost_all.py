# -*- coding: utf-8 -*-
"""
check_kit_bom_line_lost_all.py
==============================
Đếm bao nhiêu đơn bị "Đã giao" của dòng combo (kit/BoM phantom) sai vì move linh kiện mất
bom_line_id — cùng bệnh với DH125524949232179 (soát chi tiết 1 đơn:
bin/check_kit_bom_line_lost_order.py).

Nguyên nhân: đồng bộ MISA (misa_fetch_po_button/utils/misa_api_utils.py, _write_bom_from_children)
xoá hết dòng BoM của combo rồi tạo lại mỗi lần import đơn có combo đó → bom_line_id trên move cũ
bị set NULL → sale_mrp (stock.move._compute_kit_quantities) không còn đếm được move nào.

Ứng viên: dòng đơn có move linh kiện ĐÃ XONG mà bom_line_id TRỐNG (product move ≠ product dòng).
Mỗi dòng xếp vào:
  ❌ ĐANG SAI  — Đã giao đang lưu < thực giao theo linh kiện (thấy ngay trên đơn, như case trên)
  ⚠️ SẼ SAI    — đang lưu còn đúng (chưa bị tính lại), nhưng Odoo tính lại sẽ ra thấp hơn
  ✅ không ảnh hưởng — vd. move trống bom_line_id nhưng combo chưa giao / đã trả hết

In tổng, theo combo, theo tháng đặt đơn, và danh sách đơn ĐANG SAI (tối đa LIST_LIMIT).
Tiền lệch = (thực giao − đang lưu) × đơn giá sau chiết khấu, chưa thuế. "Thực" là RÒNG (giao ra
khách − khách trả có tick cập nhật SL đơn, đúng cách Odoo trừ); cột "Trả" để thấy riêng phần trả.
Dòng đơn đã huỷ bị loại; chỉ đếm move ĐÃ XONG nên phiếu chưa giao / đã huỷ không tính là đã giao.

CHỈ ĐỌC — không write/create/unlink gì, không gọi MISA (cuối script rollback cho chắc).

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_kit_bom_line_lost_all.py
"""

from collections import defaultdict

from odoo.addons.hlv_sale_delivery_planning.services.kit_qty_utils import kit_qty_from_components

LIST_LIMIT = 300
EPS = 0.001
SEP = "=" * 100

# Đúng bộ lọc sale_mrp dùng khi tính qty_delivered của kit (phía đơn bán nên in/out bị lật).
KIT_FILTERS = {
    'incoming_moves': lambda m: m._is_outgoing() and (not m.origin_returned_move_id or m.to_refund),
    'outgoing_moves': lambda m: m._is_incoming() and m.to_refund,
}
_bom_cache = {}


def money(v):
    return f"{(v or 0.0):,.0f}".replace(",", ".")


def kit_bom(line):
    key = (line.product_id.id, line.company_id.id)
    if key not in _bom_cache:
        _bom_cache[key] = env['mrp.bom']._bom_find(
            line.product_id, company_id=line.company_id.id, bom_type='phantom')[line.product_id]
    return _bom_cache[key]


def odoo_kit_delivered(line):
    """Số bộ Odoo sẽ ra nếu tính lại ngay bây giờ — chép đúng nhánh kit của sale_mrp."""
    boms = line.move_ids.filtered(lambda m: m.state != 'cancel').mapped('bom_line_id.bom_id')
    relevant = boms.filtered(lambda b: b.type == 'phantom' and (
        b.product_id == line.product_id or (b.product_tmpl_id == line.product_id.product_tmpl_id and not b.product_id)))
    relevant = relevant[:1] or kit_bom(line)
    if not relevant:
        return 0.0
    moves = line.move_ids.filtered(lambda m: m.state == 'done' and not m.scrapped)
    order_qty = line.product_uom._compute_quantity(line.product_uom_qty, relevant.product_uom_id)
    qty = moves._compute_kit_quantities(line.product_id, order_qty, relevant, KIT_FILTERS)
    return relevant.product_uom_id._compute_quantity(qty, line.product_uom)


def kit_qty_by_product(line, bom, sign_of):
    """Số bộ quy từ SL linh kiện theo SẢN PHẨM (không cần bom_line_id); sign_of(move) → +1 / -1 / 0."""
    by_product = defaultdict(float)
    for move in line.move_ids.filtered(lambda m: m.state == 'done' and not m.scrapped):
        by_product[move.product_id.id] += sign_of(move) * move.product_qty
    qty = kit_qty_from_components(bom, lambda product: by_product[product.id])
    return bom.product_uom_id._compute_quantity(qty, line.product_uom)


def real_kit_delivered(line, bom):
    """(số bộ thực giao RÒNG, số bộ khách trả).

    Như Odoo: ròng từng linh kiện (giao ra − trả có tick cập nhật SL đơn) rồi mới lấy min — trả
    lẻ 1 linh kiện cũng làm hụt bộ. Số bộ trả chỉ để hiển thị.
    """
    def net(move):
        return 1 if KIT_FILTERS['incoming_moves'](move) else -1 if KIT_FILTERS['outgoing_moves'](move) else 0

    def returned(move):
        return 1 if KIT_FILTERS['outgoing_moves'](move) else 0

    return kit_qty_by_product(line, bom, net), kit_qty_by_product(line, bom, returned)


def delivery_names(line):
    pickings = line.move_ids.filtered(lambda m: m.state == 'done' and m.location_dest_id.usage == 'customer').picking_id
    return ', '.join(f"{p.name} {str(p.date_done)[:10]}" for p in pickings.sorted('date_done')) or '-'


env.cr.execute("""
    SELECT DISTINCT sm.sale_line_id
      FROM stock_move sm
      JOIN sale_order_line sol ON sol.id = sm.sale_line_id
     WHERE sm.state = 'done'
       AND sm.bom_line_id IS NULL
       AND sm.product_id <> sol.product_id
""")
candidate_ids = [r[0] for r in env.cr.fetchall()]
lines = env['sale.order.line'].sudo().browse(candidate_ids).filtered(lambda l: l.state != 'cancel' and kit_bom(l))
print(f"\n{SEP}\n  {len(candidate_ids)} dòng đơn có move linh kiện đã xong mà TRỐNG bom_line_id — {len(lines)} dòng là kit\n{SEP}")

wrong, latent, unaffected = [], [], 0
for line in lines:
    real, returned = real_kit_delivered(line, kit_bom(line))
    stored, now = line.qty_delivered, odoo_kit_delivered(line)
    row = (line, stored, now, real, returned)
    if real - stored >= EPS:
        wrong.append(row)
    elif real - now >= EPS:
        latent.append(row)
    else:
        unaffected += 1


def summary(title, rows):
    orders = {r[0].order_id.id for r in rows}
    gap = sum((r[3] - r[1]) * r[0].price_reduce_taxexcl for r in rows)
    print(f"  {title:<14} {len(rows):>6} dòng | {len(orders):>6} đơn | tiền lệch {money(gap):>16} đ")


summary('❌ ĐANG SAI', wrong)
summary('⚠️ SẼ SAI', latent)
print(f"  ✅ không ảnh hưởng {unaffected:>3} dòng")

by_product = defaultdict(lambda: [0, set()])
by_month = defaultdict(lambda: [0, set()])
for line, *_ in wrong + latent:
    by_product[line.product_id.default_code or line.product_id.name][0] += 1
    by_product[line.product_id.default_code or line.product_id.name][1].add(line.order_id.id)
    month = str(line.order_id.date_order)[:7]
    by_month[month][0] += 1
    by_month[month][1].add(line.order_id.id)

print(f"\n{SEP}\n  THEO COMBO (đang sai + sẽ sai)\n{SEP}")
for code, (count, orders) in sorted(by_product.items(), key=lambda kv: -kv[1][0]):
    print(f"  {code:<45} {count:>5} dòng | {len(orders):>5} đơn")

print(f"\n{SEP}\n  THEO THÁNG ĐẶT ĐƠN (đang sai + sẽ sai)\n{SEP}")
for month, (count, orders) in sorted(by_month.items()):
    print(f"  {month}  {count:>5} dòng | {len(orders):>5} đơn")

print(f"\n{SEP}\n  ĐƠN ĐANG SAI (tối đa {LIST_LIMIT} dòng, mới nhất trước)\n{SEP}")
print(f"  {'Đơn':<20} {'Ngày đặt':<10} {'TT đơn':<6} {'Combo':<36} {'Đặt':>5} {'Lưu':>5} {'Thực':>5} {'Trả':>5}  Phiếu giao ra khách")
for line, stored, _now, real, returned in sorted(wrong, key=lambda r: r[0].order_id.date_order, reverse=True)[:LIST_LIMIT]:
    print(f"  {line.order_id.name:<20} {str(line.order_id.date_order)[:10]:<10} {line.order_id.state:<6} "
          f"{(line.product_id.default_code or '-')[:36]:<36} {line.product_uom_qty:>5g} {stored:>5g} {real:>5g} "
          f"{returned:>5g}  {delivery_names(line)}")

env.cr.rollback()
print(f"\n{SEP}\n  CHỈ ĐỌC — không ghi gì.\n{SEP}")
