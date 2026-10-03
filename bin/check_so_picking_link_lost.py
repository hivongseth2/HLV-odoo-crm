# -*- coding: utf-8 -*-
"""
check_so_picking_link_lost.py
=============================
Soát vì sao đơn bán mất liên kết với phiếu kho: đơn không hiện nút "Giao hàng", dòng đơn "Đã giao"
0 dù phiếu đã Hoàn tất. Case thật S02141 (Shopee 260415V2F8BHQB): phiếu "Kho Tân Sơn Nhì: Lấy hàng"
260415V2F8BHQB Hoàn tất 16/04, chứng từ gốc S02141, mà đơn ghi Đã giao 0 và không có nút phiếu.

Odoo nối đơn ↔ phiếu qua 2 sợi, đứt sợi nào hỏng chỗ đó:
  - picking.sale_id = picking.group_id.sale_id (sale_stock, stored) → nút "Giao hàng" trên đơn
    (sale.order.picking_ids là One2many theo sale_id). Đổi/xoá group_id của phiếu là mất nút.
  - move.sale_line_id → "Đã giao". Odoo CHỈ đếm move ĐÃ XONG đi VÀO kho khách (usage customer,
    _get_outgoing_incoming_moves strict) — phiếu Lấy hàng (Stock → Khu vực đóng gói) không bao giờ
    được đếm; phải có bước OUT xong. Dòng đơn bị xoá-tạo lại thì sale_line_id bị set NULL.

In ra:
  1. Đơn: procurement_group, phiếu Odoo đang nối (picking_ids), đơn khác trùng mã Shopee.
  2. Dòng đơn: ngày tạo, Đã giao đang lưu / Odoo tính lại bây giờ.
  3. MỌI phiếu liên quan — gom theo origin, tên trong PICKINGS, group, sale_id, sale_line_id, rồi
     lần theo chuỗi move_orig/move_dest (để thấy bước đóng gói/OUT dù nó đã mất liên kết) — kèm
     group, group.sale_id, người tạo/sửa cuối.
  4. Từng move: sale_line_id, group, kho đích, chuỗi trước/sau, người tạo/sửa cuối.
  5. Lịch sử tracking + ghi chú hệ thống trên đơn và các phiếu.
  6. Kết luận: sợi nào đứt và dấu vết nghi phạm.

CHỈ ĐỌC — không write/create/unlink gì (cuối script rollback cho chắc).

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_so_picking_link_lost.py
"""

from odoo.tools import html2plaintext

ORDERS = ['DH125524948218086']
# Tên phiếu biết là của đơn nhưng có thể đã đổi tên / mất origin (webhook Shopee đổi tên phiếu PICK).
PICKINGS = []
SEP = "=" * 110

Picking = env['stock.picking'].sudo()
Move = env['stock.move'].sudo()


def who(record, prefix):
    """'ngày login' của create_/write_ — để biết ai/cái gì chạm vào record cuối."""
    user = record[f'{prefix}_uid']
    return f"{str(record[f'{prefix}_date'])[:19]} {user.login or '-'}"


def group_label(group):
    if not group:
        return 'TRỐNG'
    return f"#{group.id} {group.name} (sale_id={group.sale_id.name or 'TRỐNG'})"


def odoo_delivered_now(line):
    """Đã giao Odoo sẽ ra nếu tính lại ngay — chép đúng nhánh stock_move của sale_stock."""
    outgoing, incoming = line._get_outgoing_incoming_moves()
    qty = sum(m.product_uom._compute_quantity(m.quantity, line.product_uom) for m in outgoing if m.state == 'done')
    return qty - sum(m.product_uom._compute_quantity(m.quantity, line.product_uom) for m in incoming if m.state == 'done')


def move_chain(moves):
    """Mọi move nối với `moves` qua move_orig_ids/move_dest_ids, đi cả hai chiều."""
    seen, todo = Move.browse(), moves
    while todo:
        seen |= todo
        todo = (todo.move_orig_ids | todo.move_dest_ids) - seen
    return seen


def related_pickings(order):
    group = order.procurement_group_id
    domain = ['|', '|', '|', '|',
              ('origin', 'ilike', order.name), ('name', 'in', PICKINGS),
              ('sale_id', '=', order.id), ('move_ids.sale_line_id.order_id', '=', order.id),
              ('group_id.name', '=', order.name)]
    if group:
        domain = ['|', ('group_id', '=', group.id)] + domain
    pickings = Picking.search(domain)
    return move_chain(pickings.move_ids).picking_id | pickings


def print_order(order):
    print(f"\n{SEP}\n  ĐƠN {order.name} #{order.id} | {order.partner_id.display_name} | state={order.state} | "
          f"tạo {who(order, 'create')} | sửa {who(order, 'write')}\n{SEP}")
    print(f"  procurement_group: {group_label(order.procurement_group_id)}")
    print(f"  Phiếu Odoo đang nối (picking_ids theo sale_id): {', '.join(order.picking_ids.mapped('name')) or 'KHÔNG CÓ'}")
    if 'shopee_order_ref' in order._fields and order.shopee_order_ref:
        twins = env['sale.order'].sudo().search([('shopee_order_ref', '=', order.shopee_order_ref), ('id', '!=', order.id)])
        print(f"  Mã Shopee {order.shopee_order_ref} | đơn khác trùng mã: "
              f"{', '.join(f'{t.name} #{t.id} ({t.state})' for t in twins) or 'không'}")


def print_lines(order):
    print(f"\n  {'Dòng':>7} {'Tạo':<19} {'Sản phẩm':<45} {'Đặt':>5} {'ĐG lưu':>7} {'ĐG tính':>7} {'Cách':<10} Move")
    for line in order.order_line.filtered(lambda l: not l.display_type):
        print(f"  {line.id:>7} {str(line.create_date)[:19]:<19} {(line.product_id.display_name or '')[:45]:<45} "
              f"{line.product_uom_qty:>5g} {line.qty_delivered:>7g} {odoo_delivered_now(line):>7g} "
              f"{line.qty_delivered_method or '-':<10} {', '.join(map(str, line.move_ids.ids)) or 'KHÔNG CÓ'}")


def print_pickings(order, pickings):
    print(f"\n  PHIẾU LIÊN QUAN ({len(pickings)}):")
    for p in pickings.sorted('id'):
        print(f"\n  ▸ {p.name} #{p.id} [{p.picking_type_id.display_name} | {p.picking_type_code} | "
              f"{p.picking_type_id.sequence_code}] state={p.state} xong={p.date_done or '-'}")
        print(f"    {p.location_id.complete_name} ({p.location_id.usage}) → "
              f"{p.location_dest_id.complete_name} ({p.location_dest_id.usage})")
        print(f"    origin={p.origin or '-'} | sale_id={p.sale_id.name or 'TRỐNG'} | "
              f"group={group_label(p.group_id)} | "
              f"backorder_of={p.backorder_id.name or '-'}")
        print(f"    tạo {who(p, 'create')} | sửa cuối {who(p, 'write')}")
        print(f"    {'Move':>8} {'Sản phẩm':<32} {'State':<9} {'SL':>5} {'Đích':<9} {'sale_line':<18} "
              f"{'group':<8} {'Trước':<14} {'Sau':<14} Tạo / sửa cuối")
        for m in p.move_ids.sorted('id'):
            if not m.sale_line_id:
                sl = 'TRỐNG'
            elif m.sale_line_id.order_id != order:
                sl = f'{m.sale_line_id.id}@{m.sale_line_id.order_id.name}'
            else:
                sl = str(m.sale_line_id.id)
            print(f"    {m.id:>8} {(m.product_id.default_code or m.product_id.name or '')[:32]:<32} {m.state:<9} "
                  f"{m.quantity:>5g} {m.location_dest_usage or '-':<9} {sl:<18} {str(m.group_id.id or '-'):<8} "
                  f"{','.join(map(str, m.move_orig_ids.ids)) or '-':<14} {','.join(map(str, m.move_dest_ids.ids)) or '-':<14} "
                  f"{who(m, 'create')} / {who(m, 'write')}")


def tracking_text(tv, side):
    """Giá trị cũ/mới của 1 dòng tracking — lấy cột đầu tiên có dữ liệu (char/text/số/ngày)."""
    for kind in ('char', 'text', 'datetime', 'float', 'integer'):
        value = tv[f'{side}_value_{kind}']
        if value:
            return str(value)
    return '∅'


def print_history(records):
    """Tracking (ai đổi state/tên/origin..., lúc nào) + ghi chú hệ thống (gộp phiếu, tạo từ đơn...)."""
    print("\n  LỊCH SỬ (tracking + ghi chú):")
    found = False
    for rec in records:
        messages = env['mail.message'].sudo().search(
            [('model', '=', rec._name), ('res_id', '=', rec.id)], order='date, id')
        for msg in messages:
            head = f"    {str(msg.date)[:19]} {rec.display_name:<18} {(msg.author_id.name or '-')[:22]:<22}"
            body = html2plaintext(msg.body or '').replace('\n', ' ').strip()
            if body:
                found = True
                print(f"{head} {body[:110]}")
            for tv in msg.tracking_value_ids:
                found = True
                print(f"{head} {tv.field_id.name}: {tracking_text(tv, 'old')} → {tracking_text(tv, 'new')}")
    if not found:
        print("    (không có)")


def conclude(order, pickings):
    """Gom dấu hiệu thành kết luận đọc được — sợi nào đứt, nghi phạm là gì."""
    print("\n  KẾT LUẬN:")
    group = order.procurement_group_id
    moves = pickings.move_ids
    to_customer = moves.filtered(lambda m: m.location_dest_usage == 'customer')
    lines = order.order_line.filtered(lambda l: not l.display_type)
    notes = []
    for p in pickings.filtered(lambda p: not p.sale_id):
        if not p.group_id:
            notes.append(f"{p.name}: group_id TRỐNG → mất sale_id → không hiện trên đơn.")
        elif p.group_id.sale_id != order:
            notes.append(f"{p.name}: group #{p.group_id.id} '{p.group_id.name}' trỏ đơn "
                         f"'{p.group_id.sale_id.name or 'TRỐNG'}' (đơn có group "
                         f"#{group.id if group else '-'}) → phiếu đã bị chuyển group (gộp phiếu / tách gói / tạo tay).")
        else:
            notes.append(f"{p.name}: group trỏ đúng đơn mà sale_id trống → sale_id stored chưa tính lại.")
    if not to_customer:
        notes.append("Không có move nào đi VÀO kho khách trong toàn chuỗi → Odoo không thể tính Đã giao. "
                     "Bước OUT chưa từng được tạo (tuyến 1 bước tới Khu vực đóng gói?) hoặc đã bị xoá.")
    else:
        for m in to_customer.filtered(lambda m: m.state != 'done'):
            notes.append(f"Move ra khách {m.id} ({m.picking_id.name}) đang '{m.state}' → chưa giao thì Đã giao 0 là đúng.")
        for m in to_customer.filtered(lambda m: m.state == 'done' and not m.sale_line_id):
            same_product = lines.filtered(lambda l: l.product_id == m.product_id)
            reborn = same_product.filtered(lambda l: l.create_date > m.create_date)
            hint = (f" — dòng đơn cùng sản phẩm {reborn.ids} tạo SAU move ⇒ dòng đơn đã bị xoá-tạo lại"
                    if reborn else '')
            notes.append(f"Move ra khách {m.id} ({m.picking_id.name}) ĐÃ XONG mà sale_line_id TRỐNG{hint}.")
    for m in moves.filtered(lambda m: m.sale_line_id and m.sale_line_id.order_id != order):
        notes.append(f"Move {m.id} ({m.picking_id.name}) trỏ dòng của đơn KHÁC {m.sale_line_id.order_id.name}.")
    stale = lines.filtered(lambda l: abs(l.qty_delivered - odoo_delivered_now(l)) >= 0.001)
    if stale:
        notes.append(f"Dòng {stale.ids}: Đã giao lưu ≠ Odoo tính lại → chỉ cần tính lại, không phải mất liên kết.")
    for note in notes or ["Không thấy sợi nào đứt — xem bảng move ở trên."]:
        print(f"    • {note}")


orders = env['sale.order'].sudo().search([('name', 'in', ORDERS)])
for missing in set(ORDERS) - set(orders.mapped('name')):
    print(f"❌ Không thấy đơn {missing}")
for order in orders:
    pickings = related_pickings(order)
    print_order(order)
    print_lines(order)
    print_pickings(order, pickings)
    print_history([order, *pickings])
    conclude(order, pickings)

env.cr.rollback()
print(f"\n{SEP}\n  CHỈ ĐỌC — không ghi gì.\n{SEP}")
