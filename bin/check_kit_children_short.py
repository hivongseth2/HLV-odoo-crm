# -*- coding: utf-8 -*-
"""
check_kit_children_short.py
===========================
Đọc vì sao fix_kit_children_merge.py BỎ QUA "dòng con giao lệch định mức BoM" — vd DH125524948221503
CB-M18FHPX-M18HB8-M12-18C: "M18 FHPX-0X0 giao 0 ≠ 1": pin + sạc đã giao, riêng MÁY giao 0.

Với từng combo có giá trên đơn, in:
  - định mức BoM (thành phần × SL combo) và dòng con giá 0 đang ghép được cho từng thành phần
  - MỌI dòng của đơn: mã, #id sản phẩm, thành tiền, Đặt / Đã giao, move — để thấy máy có nằm ở dòng CÓ GIÁ
    (không bị coi là dòng con) hay dòng mã khác (bản ASIA / mã cũ) không
  - MỌI hàng đã xuất trong phiếu XONG của đơn: sản phẩm, SL, nơi đến, đang thuộc dòng đơn nào — để thấy máy
    đã đi chưa và đi dưới mã nào
CHỈ ĐỌC (cuối script rollback).

Lấy đủ danh sách đơn: chạy fix_kit_children_merge.py với SKIP_SAMPLES = 50 rồi chép các đơn ở nhóm
"dòng con giao lệch định mức BoM" vào ORDERS.

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_kit_children_short.py
"""

# 20 đơn "dòng con giao lệch định mức BoM" + 1 "dòng con chưa giao đủ" (fix_kit_children_merge 02/10/2026).
ORDERS = [
    'DH125524948221560', 'DH125524948222856-BENCAM', 'DH125524948222886', 'DH125524948223417',
    'DH125524949223676', 'DH125524949223958', 'DH125524949224123', 'DH125524949224436', 'DH125524949224508',
    'DH125524949224844', 'DH125524949225101', 'DH125524949225303', 'DH125524949225751', 'DH125524949226054',
    'DH125524949226667', 'DH125524949226738', 'DH125524949227073', 'DH125524949227175', 'DH125524949227309',
    'DHSPHLV000393',
]
EPS = 0.001
SEP = "=" * 110


def kit_bom(line):
    bom = env['mrp.bom']._bom_find(line.product_id, company_id=line.company_id.id, bom_type='phantom')[line.product_id]
    if bom:
        return bom
    # BoM lưu trữ do fix_kit_children_merge tạo (combo chưa có BoM đang dùng).
    return env['mrp.bom'].sudo().with_context(active_test=False).search(
        [('product_tmpl_id', '=', line.product_id.product_tmpl_id.id), ('type', '=', 'phantom')], limit=1)


def code(product):
    return f"{product.default_code or '(không mã)'} #{product.id}{'' if product.active else ' [LƯU TRỮ]'}"


def move_summary(moves):
    if not moves:
        return '-'
    return ', '.join(f"{m.picking_id.name or '-'}:{m.state}:{m.quantity:g}" for m in moves.sorted('id'))


def print_order(order):
    print(f"\n{SEP}\n  {order.name} | {order.state} | {str(order.date_order)[:10]} | {order.partner_id.display_name[:50]}\n{SEP}")
    lines = order.order_line.filtered(lambda l: not l.display_type).sorted(lambda l: (l.sequence, l.id))
    for combo in lines.filtered(lambda l: l.product_id and abs(l.price_subtotal) >= EPS and kit_bom(l)):
        bom = kit_bom(combo)
        print(f"\n  ▸ combo {code(combo.product_id)} x{combo.product_uom_qty:g} ĐG {combo.qty_delivered:g} "
              f"| BoM #{bom.id}{'' if bom.active else ' (lưu trữ)'}")
        for bl in bom.bom_line_ids:
            need = bl.product_qty / (bom.product_qty or 1.0) * combo.product_uom_qty
            free = lines.filtered(lambda l: l != combo and l.product_id == bl.product_id and abs(l.price_subtotal) < EPS)
            priced = lines.filtered(lambda l: l != combo and l.product_id == bl.product_id and abs(l.price_subtotal) >= EPS)
            print(f"      cần {code(bl.product_id):<34} x{need:g} | dòng con giá 0: "
                  f"{', '.join(f'#{l.id} {l.qty_delivered:g}/{l.product_uom_qty:g}' for l in free) or 'KHÔNG CÓ'}"
                  f"{' | dòng CÓ GIÁ cùng mã: ' + ', '.join(f'#{l.id}' for l in priced) if priced else ''}")
    print(f"\n  Mọi dòng của đơn ({len(lines)}):")
    for line in lines:
        print(f"    #{line.id:<7} {code(line.product_id) if line.product_id else '-':<36} "
              f"{line.price_subtotal:>13,.0f} đ | {line.qty_delivered:g}/{line.product_uom_qty:g} | "
              f"{line.product_id.name[:35] if line.product_id else ''} | move: {move_summary(line.move_ids)}")
    pickings = env['stock.picking'].sudo().search(['|', ('sale_id', '=', order.id), ('origin', '=', order.name)])
    print(f"\n  Hàng đã xuất trong phiếu XONG ({', '.join(f'{p.name}({p.state})' for p in pickings.sorted('id')) or 'không phiếu'}):")
    for move in pickings.move_ids.filtered(lambda m: m.state == 'done').sorted('id'):
        owner = move.sale_line_id
        owner_label = (f"dòng #{owner.id} {owner.product_id.default_code}" if owner.order_id == order
                       else f"đơn khác {owner.order_id.name}" if owner else 'TRỐNG')
        print(f"    {move.picking_id.name:<22} {code(move.product_id):<36} x{move.quantity:g} → "
              f"{move.location_dest_id.usage:<9} | thuộc {owner_label}")


orders = env['sale.order'].sudo().search([('name', 'in', ORDERS)])
for missing in set(ORDERS) - set(orders.mapped('name')):
    print(f"❌ Không thấy đơn {missing}")
for order in orders:
    print_order(order)

env.cr.rollback()
print(f"\n{SEP}\n  CHỈ ĐỌC — không ghi gì.\n{SEP}")
