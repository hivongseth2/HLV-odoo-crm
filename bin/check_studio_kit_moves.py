# -*- coding: utf-8 -*-
"""
check_studio_kit_moves.py
=========================
In mọi move của dòng kit/combo cha (và dòng con giá 0 chứa linh kiện của nó) trong các đơn ở
ORDERS — đúng tập move mà công thức Studio mới (bin/check_studio_amount_new_formula.py) dùng làm
mẫu số khi chia giá dòng cha cho các phiếu. Dùng khi công thức mới chia nhỏ tiền 1 phiếu mà đơn
chỉ có 1 phiếu đã xuất (VD TSN/OUT/12215 của DH125524949229407: 34.164.000 → 17.082.000 đ) —
để thấy mẫu số đang cộng thêm move nào (phiếu chờ còn treo? kho khác? dòng tặng trùng linh kiện?).

Cột "tính vào mẫu": SL mà công thức cộng cho move đó (phiếu xuất xong: SL − trả; chưa xong: SL
yêu cầu; Phiếu nhập kho xong không nối phiếu xuất — hàng khách trả nhập tay: trừ; còn lại / hủy:
không tính). Công thức chia theo giá trị (SL × giá niêm yết) — cột "giá NY" để đối chiếu.

CHỈ ĐỌC — không write/create/unlink gì, không gọi MISA.

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_studio_kit_moves.py
"""

ORDERS = ['DH125524949229407', 'DH125524949226753']
SEP = "=" * 100


def money(v):
    return f"{(v or 0.0):,.0f}".replace(",", ".")


def component_ids(line):
    ids = line.product_id.bom_ids.mapped('bom_line_ids.product_id').ids
    if line.product_template_id.is_combo:
        ids += line.product_template_id.combo_product_id.mapped('product_id').ids
    return ids


def counted_qty(move):
    if move.state == 'cancel':
        return 0.0
    if move.picking_code == 'incoming':
        unlinked = move.state == 'done' and move.origin_returned_move_id.picking_code != 'outgoing'
        return -move.quantity if unlinked else 0.0
    if move.picking_code != 'outgoing':
        return 0.0
    if move.state != 'done':
        return move.product_uom_qty
    back = sum(move.returned_move_ids.filtered(lambda m: m.state == 'done').mapped('quantity'))
    return max(move.quantity - back, 0.0)


for order in env['sale.order'].sudo().search([('name', 'in', ORDERS)]):
    print(f"\n{SEP}\n  {order.name} — {order.partner_id.display_name} | trạng thái {order.state}\n{SEP}")
    for parent in order.order_line.filtered(lambda l: l.price_total > 0 and (l.product_id.bom_ids or l.product_template_id.is_combo)):
        comps = component_ids(parent)
        children = order.order_line.filtered(lambda l: l.price_total == 0 and l.product_id.id in comps)
        print(f"\n  Dòng cha [{parent.product_id.default_code}] {parent.product_id.name} | SL {parent.product_uom_qty:g}"
              f" | giá {money(parent.price_total)} | đã giao {parent.qty_delivered:g}")
        for child in children:
            print(f"    dòng con giá 0: [{child.product_id.default_code}] SL {child.product_uom_qty:g}")
        total = 0.0
        for move in (parent | children).move_ids.sorted(lambda m: (m.picking_id.name or '', m.id)):
            qty = counted_qty(move)
            total += qty
            print(f"      {move.picking_id.name or '(không phiếu)':<18} {move.picking_type_id.name or '':<28}"
                  f" {move.state:<9} [{move.product_id.default_code}] yêu cầu {move.product_uom_qty:g}"
                  f" | đã làm {move.quantity:g} | trả {sum(move.returned_move_ids.mapped('quantity')):g}"
                  f" | giá NY {money(move.product_id.lst_price)} | tính vào mẫu {qty:g}{'' if move.sale_line_id == parent else '  (dòng con)'}")
        print(f"      → mẫu số {total:g}")
print(SEP)
