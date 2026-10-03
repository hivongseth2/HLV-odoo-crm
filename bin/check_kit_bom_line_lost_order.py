# -*- coding: utf-8 -*-
"""
check_kit_bom_line_lost_order.py
================================
Soát vì sao dòng combo (kit/BoM phantom) của các đơn trong ORDERS hiện "Đã giao" = 0 dù phiếu xuất đã
hoàn tất linh kiện. Case thật DH125524949232179: KBC/OUT/09403 giao đủ 2 bộ
CB-M18FMTIW2F12-M18B5-M12-18C (2 máy + 2 pin + 2 sạc) mà dòng combo trên đơn "Đã giao" 0.

Nghi vấn: Odoo (sale_mrp → stock.move._compute_kit_quantities) chỉ đếm move linh kiện có
bom_line_id == dòng BoM hiện tại. Đồng bộ MISA (misa_fetch_po_button/utils/misa_api_utils.py,
_write_bom_from_children) XOÁ hết dòng BoM rồi tạo lại mỗi lần import đơn có combo đó →
bom_line_id trên move cũ bị set NULL → mọi đơn cũ có combo đó về "Đã giao" 0.

Với từng dòng kit của đơn, in:
  - Đã giao đang lưu / Odoo tính lại BÂY GIỜ (đúng hàm của Odoo) / thực giao theo linh kiện
  - MỌI BoM của combo, kể cả đã lưu trữ, cùng ngày tạo dòng BoM (dòng BoM tạo SAU ngày giao =
    đã bị xoá-tạo lại; combo có >1 BoM = move cũ có thể trỏ BoM khác)
  - Từng move linh kiện: phiếu, trạng thái, SL, bom_line_id (TRỐNG / trỏ BoM khác / khớp), sản
    phẩm kèm id và cờ lưu trữ (move trỏ sản phẩm cũ đã gộp/bỏ mã thì không khớp dòng BoM nào)

CHỈ ĐỌC — không write/create/unlink gì, không gọi MISA (cuối script rollback cho chắc).

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_kit_bom_line_lost_order.py
"""

from odoo.addons.hlv_sale_delivery_planning.services.kit_qty_utils import kit_qty_from_components

# Đơn cần soát (vd. đơn bị fix_kit_bom_line_relink.py BỎ QUA, hoặc combo kẹt chưa nổ BoM).
ORDERS = ['DH125524949234781']
SEP = "=" * 100

# Đúng bộ lọc sale_mrp dùng khi tính qty_delivered của kit (phía đơn bán nên in/out bị lật).
KIT_FILTERS = {
    'incoming_moves': lambda m: m._is_outgoing() and (not m.origin_returned_move_id or m.to_refund),
    'outgoing_moves': lambda m: m._is_incoming() and m.to_refund,
}


def kit_bom(line):
    return env['mrp.bom']._bom_find(line.product_id, company_id=line.company_id.id, bom_type='phantom')[line.product_id]


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


def real_kit_delivered(line, bom):
    """Số bộ thực giao suy từ SL linh kiện theo SẢN PHẨM — không cần bom_line_id."""
    moves = line.move_ids.filtered(lambda m: m.state == 'done' and not m.scrapped)
    by_product = {}
    for move in moves:
        sign = 1 if KIT_FILTERS['incoming_moves'](move) else -1 if KIT_FILTERS['outgoing_moves'](move) else 0
        by_product[move.product_id.id] = by_product.get(move.product_id.id, 0.0) + sign * move.product_qty
    qty = kit_qty_from_components(bom, lambda product: by_product.get(product.id, 0.0))
    return bom.product_uom_id._compute_quantity(qty, line.product_uom) if bom else 0.0


def link_label(move, bom):
    if not move.bom_line_id:
        return 'TRỐNG'
    if move.bom_line_id in bom.bom_line_ids:
        return f'khớp ({move.bom_line_id.id})'
    return f'BoM khác {move.bom_line_id.bom_id.id} ({move.bom_line_id.id})'


def product_label(product):
    """Mã + id + tên; đánh dấu sản phẩm đã lưu trữ — move có thể trỏ sản phẩm cũ đã bị gộp/xoá mã."""
    archived = '' if product.active else ' [LƯU TRỮ]'
    return f"{product.default_code or '(không mã)'} #{product.id} {product.name[:40]}{archived}"


def print_all_boms(product):
    """Mọi BoM của sản phẩm, KỂ CẢ đã lưu trữ — combo có >1 BoM thì move cũ có thể trỏ BoM khác."""
    boms = env['mrp.bom'].with_context(active_test=False).search([
        ('product_tmpl_id', '=', product.product_tmpl_id.id),
        '|', ('product_id', '=', False), ('product_id', '=', product.id),
    ])
    for bom in boms:
        state = 'đang dùng' if bom.active else 'LƯU TRỮ'
        print(f"    BoM {bom.id} [{bom.type}, {state}, seq {bom.sequence}] {bom.code or '-'} | tạo {bom.create_date} | sửa {bom.write_date}")
        for bl in bom.bom_line_ids:
            print(f"      dòng BoM {bl.id:>7}  {product_label(bl.product_id):<60} x{bl.product_qty:g}  tạo {bl.create_date}")


def print_order(order):
    print(f"\n{SEP}\n  {order.name} | {order.partner_id.display_name} | state={order.state} | invoice_status={order.invoice_status}\n{SEP}")
    kit_lines = order.order_line.filtered(lambda l: not l.display_type and l.product_id and kit_bom(l))
    if not kit_lines:
        print("  Đơn không có dòng kit nào.")
    for line in kit_lines:
        bom = kit_bom(line)
        stored, now, real = line.qty_delivered, odoo_kit_delivered(line), real_kit_delivered(line, bom)
        verdict = '✅ đúng' if abs(stored - real) < 0.001 and abs(now - real) < 0.001 else \
            '❌ ĐANG SAI' if abs(stored - real) >= 0.001 else '⚠️ đang đúng nhưng tính lại sẽ SAI'
        print(f"\n  [{line.product_id.default_code}] {line.product_id.name}")
        print(f"    Đặt {line.product_uom_qty:g} | Đã giao lưu {stored:g} | Odoo tính lại {now:g} | thực giao {real:g} → {verdict}")
        print(f"    BoM Odoo đang chọn: {bom.id}")
        print_all_boms(line.product_id)
        print(f"    {'Phiếu':<18} {'Tạo move':<19} {'Ngày xong':<19} {'Trạng thái':<10} {'SL':>6}  {'bom_line_id':<22} Linh kiện")
        for move in line.move_ids.sorted('id'):
            print(f"    {move.picking_id.name or '-':<18} {str(move.create_date)[:19]:<19} {str(move.date)[:19]:<19} {move.state:<10} "
                  f"{move.product_qty:>6g}  {link_label(move, bom):<22} {product_label(move.product_id)}")
        # Move xuất CHÍNH mã combo = lúc xác nhận đơn combo chưa có BoM nên Odoo không nổ ra linh kiện;
        # combo không có tồn nên phiếu kẹt chờ hàng mãi. Move này vốn không bao giờ có bom_line_id.
        unexploded = line.move_ids.filtered(lambda m: m.product_id == line.product_id and m.state not in ('done', 'cancel'))
        if unexploded:
            print(f"    → ⛔ {len(unexploded)} move đang xuất CHÍNH mã combo (tạo {str(min(unexploded.mapped('create_date')))[:19]}) — "
                  "đơn xác nhận khi combo CHƯA có BoM, kho không thể giao. Sửa: bin/fix_kit_unexploded_move.py")
        # Move LINH KIỆN tạo TRƯỚC dòng BoM hiện tại mà trống bom_line_id = lúc tạo nó trỏ dòng BoM cũ, dòng đó đã bị xoá.
        first_bom_line = min(bom.bom_line_ids.mapped('create_date')) if bom.bom_line_ids else None
        orphaned = line.move_ids.filtered(lambda m: m.product_id != line.product_id and not m.bom_line_id
                                          and first_bom_line and m.create_date < first_bom_line)
        if orphaned:
            print(f"    → {len(orphaned)} move tạo TRƯỚC dòng BoM hiện tại ({first_bom_line}) và đã mất bom_line_id: "
                  "BoM đã bị xoá-tạo lại sau khi xác nhận đơn.")


orders = env['sale.order'].sudo().search([('name', 'in', ORDERS)])
for missing in set(ORDERS) - set(orders.mapped('name')):
    print(f"❌ Không thấy đơn {missing}")
for order in orders:
    print_order(order)

env.cr.rollback()
print(f"\n{SEP}\n  CHỈ ĐỌC — không ghi gì.\n{SEP}")
