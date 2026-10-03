# -*- coding: utf-8 -*-
"""
check_order_delivery_triage.py
==============================
Soát nhanh nhiều đơn "giao rồi mà Đã giao vẫn thiếu" — mỗi đơn một khối ngắn, để log không bị shell
cắt (bản chi tiết từng move + lịch sử: bin/check_so_picking_link_lost.py).

Các nghi phạm đã gặp, script dò từng cái:
  - Dòng đơn bị XOÁ-TẠO LẠI (ghi chú "Đồng bộ (xoá & tạo lại)" trên đơn): move đã giao mất
    sale_line_id (set NULL khi dòng cũ bị xoá) → dòng mới Đã giao 0. Dấu hiệu: dòng tạo SAU ngày giao,
    phiếu của đơn có move XONG mà sale_line_id trống cùng sản phẩm → gắn lại được.
  - Phiếu mất liên kết đơn (group_id / sale_id đổi) → không hiện trên nút "Giao hàng".
  - Move trỏ dòng của đơn KHÁC.
  - Phiếu đã HUỶ mà đơn vẫn "sale" (vd đơn Shopee đã huỷ/hoàn) → chưa giao thật.
  - Dòng combo (kit) → soát bằng bin/check_kit_children_lines.py / check_kit_bom_line_lost_order.py.

Mỗi đơn in: phiếu liên quan (trạng thái, có nối đơn không), các dòng còn thiếu (Đặt / Đã giao lưu /
Odoo tính lại / move của dòng / move mồ côi cùng sản phẩm) và kết luận.

CHỈ ĐỌC — không write/create/unlink gì (cuối script rollback cho chắc).

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_order_delivery_triage.py
"""

from collections import defaultdict
from datetime import timedelta

ORDERS = ['DH115524948214442', 'DH125524948216340']
EPS = 0.001
SEP = "=" * 100

Picking = env['stock.picking'].sudo()
Bom = env['mrp.bom'].sudo()


def kit_bom(line):
    return Bom._bom_find(line.product_id, company_id=line.company_id.id, bom_type='phantom')[line.product_id]


def odoo_delivered_now(line):
    """Đã giao Odoo sẽ ra nếu tính lại ngay — chép đúng nhánh stock_move của sale_stock (dòng thường)."""
    outgoing, incoming = line._get_outgoing_incoming_moves()
    qty = sum(m.product_uom._compute_quantity(m.quantity, line.product_uom) for m in outgoing if m.state == 'done')
    return qty - sum(m.product_uom._compute_quantity(m.quantity, line.product_uom) for m in incoming if m.state == 'done')


def state_summary(moves):
    """'done 2, cancel 1 [KBC/OUT/1(done)]', '-' nếu không có move."""
    if not moves:
        return '-'
    counts = defaultdict(int)
    for move in moves:
        counts[move.state] += 1
    pickings = ', '.join(f"{p.name}({p.state})" for p in moves.picking_id.sorted('id'))
    return f"{', '.join(f'{k} {v}' for k, v in sorted(counts.items()))} [{pickings or 'không phiếu'}]"


def related_pickings(order):
    domain = ['|', '|', ('sale_id', '=', order.id), ('origin', 'ilike', order.name),
              ('move_ids.sale_line_id.order_id', '=', order.id)]
    if order.procurement_group_id:
        domain = ['|', ('group_id', '=', order.procurement_group_id.id)] + domain
    return Picking.search(domain)


def rebuild_notes(order):
    """Ghi chú 'xoá & tạo lại' trên đơn — dòng đơn bị xoá-tạo lại thì move cũ mất sale_line_id."""
    messages = env['mail.message'].sudo().search([
        ('model', '=', 'sale.order'), ('res_id', '=', order.id), ('body', 'ilike', 'tạo lại'),
    ], order='date')
    return ', '.join(str(m.date)[:16] for m in messages)


def to_customer_done(moves):
    return moves.filtered(lambda m: m.state == 'done' and m.location_dest_usage == 'customer')


def money(v):
    return f"{(v or 0.0):,.0f}".replace(",", ".")


def delivered_elsewhere(line, days=60):
    """Move XONG ra khách cùng sản phẩm, cùng khách (công ty mẹ), ±days quanh ngày đặt, KHÔNG thuộc đơn này
    — dòng chưa từng sinh move thì xem hàng có đi qua đơn/phiếu khác không."""
    order = line.order_id
    partner = order.partner_id.commercial_partner_id
    moves = env['stock.move'].sudo().search([
        ('product_id', '=', line.product_id.id), ('state', '=', 'done'), ('location_dest_usage', '=', 'customer'),
        ('picking_id.partner_id', 'child_of', partner.id),
        ('date', '>=', order.date_order - timedelta(days=days)), ('date', '<=', order.date_order + timedelta(days=days)),
    ], limit=5)
    moves = moves.filtered(lambda m: m.sale_line_id.order_id != order)
    if not moves:
        return 'không thấy'
    return ', '.join(f"{m.picking_id.name} {str(m.date)[:10]} x{m.quantity:g} ({m.sale_line_id.order_id.name or 'không đơn'})"
                     for m in moves)


def line_label(move, order):
    """Dòng đơn mà move đang thuộc: mã sản phẩm của dòng, TRỐNG, hoặc dòng của đơn khác."""
    line = move.sale_line_id
    if not line:
        return 'TRỐNG'
    if line.order_id != order:
        return f"đơn khác {line.order_id.name}"
    return f"dòng #{line.id} {line.product_id.default_code or line.product_id.name[:20]}"


def print_done_contents(order, moves):
    """Hàng thật sự đã đi trong các phiếu xong của đơn — để thấy dòng đơn lệch mã với hàng xuất."""
    done = moves.filtered(lambda m: m.state == 'done')
    print(f"      hàng trong phiếu đã xong ({len(done)} move):")
    for move in done.sorted('id'):
        product = move.product_id
        archived = '' if product.active else ' [LƯU TRỮ]'
        print(f"        {move.picking_id.name:<20} {(product.default_code or '(không mã)')[:24]:<24} #{product.id}"
              f"{archived} x{move.quantity:g} → {move.location_dest_id.usage} | thuộc {line_label(move, order)}")


def print_order(order):
    pickings = related_pickings(order)
    moves = pickings.move_ids
    orphans = moves.filtered(lambda m: not m.sale_line_id and m.state != 'cancel')
    foreign = moves.filtered(lambda m: m.sale_line_id and m.sale_line_id.order_id != order)
    rebuilt = rebuild_notes(order)
    rebuilt_note = f" | xoá-tạo lại: {rebuilt}" if rebuilt else ''
    print(f"\n  ▸ {order.name} | {order.state} | đặt {str(order.date_order)[:10]} | "
          f"{order.partner_id.display_name[:50]}{rebuilt_note}")
    picking_labels = [f"{p.name}({p.state}{'' if p.sale_id == order else ', KHÔNG nối đơn'})"
                      for p in pickings.sorted('id')]
    print(f"      phiếu: {', '.join(picking_labels) or 'KHÔNG CÓ'}")
    notes, unexplained = [], False
    lines = order.order_line.filtered(lambda l: not l.display_type and l.product_id)
    for line in lines:
        code = line.product_id.default_code or line.product_id.name[:30]
        manual = line.qty_delivered_method != 'stock_move'
        is_kit = bool(kit_bom(line))
        now = line.qty_delivered if (is_kit or manual) else odoo_delivered_now(line)
        if line.qty_delivered >= line.product_uom_qty - EPS and abs(now - line.qty_delivered) < EPS:
            continue
        same_orphans = to_customer_done(orphans.filtered(lambda m: m.product_id == line.product_id))
        orphan_note = f" | mồ côi ra khách {sum(same_orphans.mapped('quantity')):g}" if same_orphans else ''
        kind_note = f" | loại {line.product_id.type}, Đã giao {line.qty_delivered_method}" if manual else ''
        print(f"      {code[:30]:<30} đặt {line.product_uom_qty:g} | "
              f"ĐG lưu {line.qty_delivered:g} | tính lại {now:g} | dòng tạo {str(line.create_date)[:16]} | "
              f"move: {state_summary(line.move_ids)}{orphan_note}{kind_note}")
        if manual:
            # Combo loại dịch vụ/combo: không sinh move, Đã giao nhập tay — hàng đi qua dòng con giá 0.
            notes.append(f"{code}: dòng {line.product_id.type} (Đã giao nhập tay, không có move) — nếu là combo "
                         "có dòng con đã giao đủ → đặt Đã giao = SL bằng fix_kit_children_merge.py")
        elif is_kit:
            notes.append(f"{code}: dòng combo → soát bằng check_kit_children_lines.py")
        elif same_orphans:
            first_done = min(same_orphans.mapped('date'))
            reborn = ' (dòng tạo SAU ngày giao ⇒ bị xoá-tạo lại)' if line.create_date > first_done else ''
            notes.append(f"{line.product_id.default_code}: có move ĐÃ GIAO mà mất sale_line_id{reborn} → gắn lại được")
        elif not line.move_ids and to_customer_done(moves.filtered(lambda m: m.product_id == line.product_id)):
            notes.append(f"{line.product_id.default_code}: dòng không có move, nhưng phiếu của đơn đã giao sản phẩm này "
                         "(move trỏ dòng khác?)")
        elif line.move_ids and not line.move_ids.filtered(lambda m: m.state != 'cancel'):
            notes.append(f"{line.product_id.default_code}: mọi move đã HUỶ → chưa giao thật (đơn huỷ/hoàn bên sàn?)")
        elif abs(now - line.qty_delivered) >= EPS:
            notes.append(f"{line.product_id.default_code}: Đã giao lưu ≠ tính lại → chỉ cần tính lại")
        elif line.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
            notes.append(f"{code}: còn move chưa xong → đang chờ giao (bình thường)")
        else:
            unexplained = True
            notes.append(f"{code}: dòng {money(line.price_subtotal)} đ chưa từng sinh move, phiếu của đơn cũng không "
                         f"giao sản phẩm này | giao cho khách này ở chỗ khác: {delivered_elsewhere(line)}")
    if unexplained:
        print_done_contents(order, moves)
    for move in foreign:
        notes.append(f"move {move.id} ({move.picking_id.name}) trỏ dòng của đơn KHÁC {move.sale_line_id.order_id.name}")
    if not notes:
        notes.append("không thấy dòng nào thiếu Đã giao")
    for note in notes:
        print(f"      • {note}")


orders = env['sale.order'].sudo().search([('name', 'in', ORDERS)])
print(f"\n{SEP}\n  SOÁT NHANH ĐÃ GIAO — {len(orders)}/{len(ORDERS)} đơn\n{SEP}")
for name in ORDERS:
    order = orders.filtered(lambda o: o.name == name)
    if order:
        print_order(order)
    else:
        print(f"\n  ▸ {name} — KHÔNG THẤY ĐƠN")

env.cr.rollback()
print(f"\n{SEP}\n  CHỈ ĐỌC — không ghi gì.\n{SEP}")
