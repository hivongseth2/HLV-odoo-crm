# -*- coding: utf-8 -*-
"""
check_kit_uom_mismatch.py
=========================
Đọc vì sao gộp dòng con về combo (bin/fix_kit_children_merge.py) lỗi
"The unit of measure Cái defined on the order line doesn't belong to the same category as the unit of
measure Cái defined on the product" — case CB-48-32-4364D-1MUI (DH125524948221184 ...): hai ĐVT cùng tên
"Cái" nhưng khác nhóm (uom.category) → uom._compute_quantity từ chối quy đổi.

In ra mọi ĐVT dính vào phép gộp (id + nhóm, để thấy hai "Cái" khác nhau ở đâu):
  - dòng combo (ĐVT dòng) và sản phẩm combo (ĐVT sản phẩm)
  - Combo Items / BoM: ĐVT từng thành phần
  - từng dòng con: ĐVT dòng, ĐVT sản phẩm; từng move của dòng con: ĐVT move
  - mọi ĐVT tên "Cái" trong hệ thống
Rồi gộp THỬ đúng như script gộp trong savepoint và in traceback: dòng code Odoo nào đang quy đổi từ ĐVT
nào sang ĐVT nào. Rollback — KHÔNG ghi gì.

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_kit_uom_mismatch.py
"""

import traceback

ORDERS = ['DH125524948221184']
EPS = 0.001
SEP = "=" * 110


class _Rollback(Exception):
    """Ném ra cuối gộp thử để savepoint hoàn tác."""


def uom_label(uom):
    if not uom:
        return '-'
    return f"{uom.name} #{uom.id} [nhóm {uom.category_id.name} #{uom.category_id.id}, {uom.uom_type}, x{uom.factor:g}]"


def components(line):
    """(sản phẩm → ĐVT thành phần) theo BoM nếu có (kể cả lưu trữ), không thì theo Combo Items."""
    tmpl = line.product_id.product_tmpl_id
    bom = env['mrp.bom'].sudo().with_context(active_test=False).search(
        [('product_tmpl_id', '=', tmpl.id), ('type', '=', 'phantom')], limit=1)
    if bom:
        return bom, {bl.product_id: bl.product_uom_id for bl in bom.bom_line_ids}
    if 'combo_product_id' in tmpl._fields:
        return bom, {item.product_id: item.product_id.uom_id for item in tmpl.combo_product_id}
    return bom, {}


def print_uoms(line):
    product = line.product_id
    bom, comps = components(line)
    print(f"    dòng combo #{line.id}: ĐVT dòng {uom_label(line.product_uom)}")
    print(f"    sản phẩm combo #{product.id} {product.default_code}: ĐVT {uom_label(product.uom_id)} "
          f"| ĐVT mua {uom_label(product.uom_po_id)} | active={product.active}")
    if bom:
        print(f"    BoM #{bom.id} active={bom.active} ({bom.code or '-'}): ĐVT BoM {uom_label(bom.product_uom_id)}")
    else:
        print("    chưa có BoM — thành phần lấy theo Combo Items")
    for comp, comp_uom in comps.items():
        print(f"      thành phần {comp.default_code} #{comp.id}: ĐVT dòng BoM/item {uom_label(comp_uom)} | "
              f"ĐVT sản phẩm {uom_label(comp.uom_id)}")
    children = (line.order_id.order_line - line).filtered(
        lambda l: not l.display_type and abs(l.price_subtotal) < EPS and l.product_id in list(comps))
    for child in children:
        print(f"    dòng con #{child.id} {child.product_id.default_code} {child.qty_delivered:g}/{child.product_uom_qty:g}: "
              f"ĐVT dòng {uom_label(child.product_uom)} | ĐVT sản phẩm {uom_label(child.product_id.uom_id)}")
        for move in child.move_ids.sorted('id'):
            print(f"      move {move.id} {move.picking_id.name or '-'} {move.state}: ĐVT move {uom_label(move.product_uom)}")
    return children


def try_merge(line, children):
    """Gộp thử như fix_kit_children_merge (chuyển move + tính lại) để bắt đúng chỗ quy đổi lỗi."""
    bom, comps = components(line)
    if not bom:
        bom = env['mrp.bom'].sudo().with_context(active_test=False).create({
            'product_tmpl_id': line.product_id.product_tmpl_id.id, 'type': 'phantom', 'product_qty': 1.0,
            'active': False, 'code': 'gộp thử (check_kit_uom_mismatch)',
            'bom_line_ids': [(0, 0, {'product_id': p.id, 'product_qty': it.product_quantity,
                                     'product_uom_id': p.uom_id.id})
                             for it in line.product_id.product_tmpl_id.combo_product_id for p in it.product_id],
        })
        print(f"    (gộp thử với BoM lưu trữ tạm #{bom.id}, ĐVT BoM {uom_label(bom.product_uom_id)})")
    by_product = {bl.product_id.id: bl for bl in bom.bom_line_ids}
    try:
        with env.cr.savepoint():
            for child in children:
                child.move_ids.filtered(lambda m: m.state != 'cancel').write(
                    {'sale_line_id': line.id, 'bom_line_id': by_product[child.product_id.id].id})
            env.add_to_compute(env['sale.order.line']._fields['qty_delivered'], line | children)
            (line | children).flush_recordset(['qty_delivered'])
            print(f"    gộp thử OK — combo Đã giao {line.qty_delivered:g}/{line.product_uom_qty:g}")
            raise _Rollback()
    except _Rollback:
        pass
    except Exception:  # noqa: BLE001 — cần đúng traceback để biết chỗ quy đổi ĐVT
        frames = traceback.format_exc().strip().splitlines()
        print("    GỘP THỬ LỖI — traceback (phần cuối, thấy dòng Odoo đang quy đổi ĐVT):")
        for frame in frames[-14:]:
            print(f"      {frame}")


orders = env['sale.order'].sudo().search([('name', 'in', ORDERS)])
print(f"\n{SEP}\n  ĐVT 'Cái' trong hệ thống:")
for uom in env['uom.uom'].sudo().with_context(active_test=False).search([('name', 'ilike', 'cái')]):
    print(f"    {uom_label(uom)} active={uom.active}")
for order in orders:
    print(f"\n{SEP}\n  {order.name} | {order.state}\n{SEP}")
    combo_lines = order.order_line.filtered(
        lambda l: l.product_id and abs(l.price_subtotal) >= EPS and l.qty_delivered < l.product_uom_qty - EPS
        and components(l)[1])
    for line in combo_lines:
        print(f"\n  [{line.product_id.default_code}] x{line.product_uom_qty:g}")
        children = print_uoms(line)
        if children:
            try_merge(line, children)

env.cr.rollback()
print(f"\n{SEP}\n  CHỈ ĐỌC — gộp thử trong savepoint rồi hoàn tác, không ghi gì.\n{SEP}")
