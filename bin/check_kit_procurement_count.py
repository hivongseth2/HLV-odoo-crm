# -*- coding: utf-8 -*-
"""
check_kit_procurement_count.py
==============================
Đọc vì sao gộp dòng con về combo (bin/fix_kit_children_merge.py) ra "đặt kho N bộ ≠ SL đặt" — case
DH125524949225123: CB-M12FPTR-M12B2-C12C x1, gộp xong Đã giao 1 nhưng _get_qty_procurement ra 2.

Làm đúng như script gộp TRONG savepoint (chuyển move dòng con sang dòng combo + gắn bom_line_id), rồi
chạy đúng logic Odoo đếm số bộ đã đặt kho (sale_mrp._get_qty_procurement →
stock.move._compute_kit_quantities với _get_incoming_outgoing_moves_filter), in TỪNG move:
  - có lọt bộ lọc "incoming" không (rule kích hoạt + đích cuối là khách + không phải move trả) và vì sao
  - có bị loại vì là bước TRƯỚC của move khác (move_orig_ids) không → chỉ move "cuối chuỗi" được đếm
  - SL được đếm (move chưa xong đếm SL yêu cầu, xong đếm SL thực)
Cuối mỗi linh kiện: tổng được đếm / định mức = số bộ. Rồi rollback — KHÔNG ghi gì.

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_kit_procurement_count.py
"""

ORDERS = ['DH125524949224365']
EPS = 0.001
SEP = "=" * 110


class _Rollback(Exception):
    """Ném ra cuối explain_line để savepoint hoàn tác thao tác gộp thử."""


def kit_bom(line):
    return env['mrp.bom']._bom_find(line.product_id, company_id=line.company_id.id, bom_type='phantom')[line.product_id]


def children_of(line, bom):
    components = bom.bom_line_ids.product_id
    return (line.order_id.order_line - line).filtered(
        lambda l: not l.display_type and abs(l.price_subtotal) < EPS and l.product_id in components)


def ids(records):
    return ','.join(map(str, records.ids)) or '-'


def counted_qty(move):
    """Đúng get_qty trong _compute_kit_quantities: đã lấy (picked) → SL thực, chưa → SL yêu cầu."""
    if move.picked:
        return move.product_uom._compute_quantity(move.quantity, move.product_id.uom_id, rounding_method='HALF-UP')
    return move.product_qty


def why_not_incoming(move, triggering_rule_ids):
    reasons = []
    if move.state == 'cancel':
        reasons.append('đã huỷ')
    if move.scrapped:
        reasons.append('phế')
    if move.rule_id.id not in triggering_rule_ids:
        reasons.append(f"rule {move.rule_id.display_name or '-'} không kích hoạt")
    if move.location_final_id.usage != 'customer':
        reasons.append(f"đích cuối {move.location_final_id.usage or '-'}")
    if move.origin_returned_move_id and not move.to_refund:
        reasons.append('move trả không cập nhật SL đơn')
    return ', '.join(reasons)


def print_pickings(order):
    pickings = env['stock.picking'].sudo().search([
        '|', ('sale_id', '=', order.id), ('origin', '=', order.name)])
    print(f"\n  Phiếu của đơn ({len(pickings)}):")
    for p in pickings.sorted('id'):
        print(f"    {p.name:<20} #{p.id:<7} {p.picking_type_id.display_name[:30]:<30} {p.state:<9} "
              f"{p.location_id.complete_name} → {p.location_dest_id.complete_name} | xong {p.date_done or '-'}")


def explain_line(line):
    bom = kit_bom(line)
    if not bom:
        print("    combo chưa có BoM đang dùng — script này chỉ soát combo có BoM")
        return
    children = children_of(line, bom)
    bom_line_by_product = {bl.product_id.id: bl for bl in bom.bom_line_ids}
    with env.cr.savepoint():
        for child in children:
            child.move_ids.filtered(lambda m: m.state != 'cancel').write(
                {'sale_line_id': line.id, 'bom_line_id': bom_line_by_product[child.product_id.id].id})
        line.invalidate_recordset(['move_ids'])
        filters = line._get_incoming_outgoing_moves_filter()
        # Tái dựng triggering_rule_ids y như sale_mrp để in lý do (filters chỉ trả lambda).
        triggering_rule_ids, seen_wh, seen_bom = [], set(), set()
        for move in line.move_ids.sorted('id'):
            if move.bom_line_id.bom_id.id in seen_bom:
                triggering_rule_ids.append(move.rule_id.id)
            elif move.warehouse_id.id not in seen_wh:
                triggering_rule_ids.append(move.rule_id.id)
                seen_wh.add(move.warehouse_id.id)
                if move.bom_line_id and move.bom_line_id.bom_id.type == 'phantom':
                    seen_bom.add(move.bom_line_id.bom_id.id)
        rule_names = ', '.join(env['stock.rule'].sudo().browse(set(triggering_rule_ids)).mapped('display_name'))
        print(f"    rule kích hoạt: {rule_names or '-'}")
        moves = line.move_ids.filtered(lambda m: m.state != 'cancel' and not m.scrapped)
        ratios = []
        for bom_line in bom.bom_line_ids:
            bl_moves = moves.filtered(lambda m: m.bom_line_id == bom_line)
            incoming = bl_moves.filtered(filters['incoming_moves'])
            final_in = incoming - incoming.move_orig_ids
            outgoing = bl_moves.filtered(filters['outgoing_moves'])
            final_out = outgoing - outgoing.move_orig_ids
            per_kit = bom_line.product_qty / (bom.product_qty or 1.0)
            print(f"\n    ▸ {bom_line.product_id.default_code} (định mức {per_kit:g}/bộ) — {len(bl_moves)} move:")
            print(f"      {'Move':>8} {'Phiếu':<18} {'State':<9} {'SL':>5} {'Rule':<28} {'Đích cuối':<10} "
                  f"{'Trước':<16} {'Sau':<16} Đếm?")
            for move in line.move_ids.filtered(lambda m: m.bom_line_id == bom_line or (
                    m.product_id == bom_line.product_id)).sorted('id'):
                if move in final_in:
                    verdict = f"ĐẾM +{counted_qty(move):g}"
                elif move in final_out:
                    verdict = f"TRỪ -{counted_qty(move):g} (trả hàng)"
                elif move in incoming:
                    verdict = "loại: là bước TRƯỚC của move " + ids(move.move_dest_ids & incoming)
                else:
                    verdict = "loại: " + (why_not_incoming(move, triggering_rule_ids) or 'không khớp bộ lọc')
                print(f"      {move.id:>8} {move.picking_id.name or '-':<18} {move.state:<9} {move.product_uom_qty:>5g} "
                      f"{(move.rule_id.display_name or '-')[:28]:<28} {move.location_final_id.usage or '-':<10} "
                      f"{ids(move.move_orig_ids)[:16]:<16} {ids(move.move_dest_ids)[:16]:<16} {verdict}")
            qty = sum(final_in.mapped(counted_qty)) - sum(final_out.mapped(counted_qty))
            ratio = qty / per_kit if per_kit else 0.0
            ratios.append(ratio)
            print(f"      → đếm {qty:g} / {per_kit:g} = {ratio:g} bộ")
        print(f"\n    Odoo _get_qty_procurement (thật, sau gộp): {line._get_qty_procurement():g} | "
              f"min theo bảng trên: {min(ratios) if ratios else 0:g} | SL đặt {line.product_uom_qty:g}")
        raise _Rollback()  # hoàn tác gộp thử


orders = env['sale.order'].sudo().search([('name', 'in', ORDERS)])
for order in orders:
    print(f"\n{SEP}\n  {order.name} | {order.state}\n{SEP}")
    print_pickings(order)
    for line in order.order_line.filtered(lambda l: l.product_id and kit_bom(l) and children_of(l, kit_bom(l))):
        print(f"\n  [{line.product_id.default_code}] x{line.product_uom_qty:g} — gộp thử dòng con: "
              f"{', '.join(children_of(line, kit_bom(line)).product_id.mapped('default_code'))}")
        try:
            explain_line(line)
        except _Rollback:
            pass  # savepoint đã hoàn tác thao tác gộp thử

env.cr.rollback()
print(f"\n{SEP}\n  CHỈ ĐỌC — gộp thử trong savepoint rồi hoàn tác, không ghi gì.\n{SEP}")
