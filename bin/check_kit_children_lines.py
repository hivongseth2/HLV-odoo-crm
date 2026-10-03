# -*- coding: utf-8 -*-
"""
check_kit_children_lines.py
===========================
Đếm các đơn mà combo bị "xổ" thành dòng con NGAY TRÊN ĐƠN, cạnh dòng combo cha — cùng bệnh với
DH125524949234781: đơn có dòng combo CB-M18ONEFHIWF1-2.M18FB8-M12-18FC (giá 15tr, SL 1) + 3 dòng con
giá 0 (máy, 2 pin, sạc). Kho giao 3 dòng con (KBC/PICK → PACK → OUT Hoàn tất); dòng combo sinh move
xuất CHÍNH mã combo (KBC/PICK/10754 "Đang chờ") — combo không có tồn nên treo mãi, Đã giao 0.

Nguồn: trước commit cf9dda1fe (10/08/2026) đồng bộ đơn MISA (misa_fetch_po_button
sale_order_misa_sync) chỉ bỏ dòng con khi combo ĐÃ có BoM; combo chưa có BoM thì giữ cả dòng cha lẫn
dòng con (IsChildProduct). Từ bản đó mới tự tạo Kit BoM rồi bỏ dòng con.

Dòng con = dòng KHÁC trên cùng đơn, thành tiền 0, sản phẩm là linh kiện trong BoM combo. Combo chưa có
BoM thì lấy linh kiện từ Combo Items (combo_product); không khai luôn thì đoán dòng con = các dòng thành
tiền 0 liền sau dòng combo (ghi rõ "ĐOÁN"). Combo nhận diện bằng BoM / mã 'CB…' / tên 'Combo…' / is_combo.

Xếp mỗi dòng combo vào:
  A. KẸT, con đã giao   — move mã combo còn treo, dòng con giao đủ (case trên). Hàng đã đi; chỉ cần
                          huỷ move treo. KHÔNG nổ lại BoM (bin/fix_kit_unexploded_move.py) — sẽ giao trùng.
  B. KẸT, con chưa giao — move mã combo treo, dòng con chưa giao đủ.
  C. GIAO TRÙNG         — dòng combo đã nổ BoM và giao linh kiện, dòng con CŨNG đã giao.
  D. SẮP GIAO TRÙNG     — dòng combo đã nổ BoM (move linh kiện đang chờ) trong khi dòng con cũng có move.
  E1–E6. còn lại        — tách nhỏ (dòng con rỗng / combo không sinh move / move combo đã huỷ tay /
                          combo đã giao mà dòng con còn chờ ảo / khác); in vài dòng mẫu mỗi nhóm.
Nhóm C đánh dấu "con SL 0" khi dòng con đặt 0 mà có giao — thường là MISA đặt SL dòng về 0 SAU khi
đã giao, hoặc move bị gán nhầm dòng; chưa chắc là giao trùng, phải xem phiếu.

CHỈ ĐỌC — không write/create/unlink gì, không gọi MISA (cuối script rollback cho chắc).

ORDERS: có danh sách thì chỉ soát các đơn đó, in MỌI dòng combo kèm chi tiết (move mã combo, move
linh kiện, phiếu của dòng con, BoM tạo lúc nào) và cách sửa; đơn không thấy combo có dòng con cũng báo.

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_kit_children_lines.py
"""

from collections import defaultdict

# Soát riêng các đơn này (in chi tiết từng dòng combo); để [] = quét mọi đơn đã xác nhận.
ORDERS = [
    'DH125524949224516', 'DH115524948214442', 'DH125524948220957', 'DHSPMI000511', 'DHSPMI000388',
    'DHSPMI000053', 'DH125524948219092', 'DH125524949232196', 'DH125524948216340', 'DHSPMI000153',
    'DH115524948216078',
]
LIST_LIMIT = 150  # dòng in tối đa mỗi nhóm — shell cắt log dài
EPS = 0.001
SEP = "=" * 100
OPEN = ('done', 'cancel')

SaleLine = env['sale.order.line'].sudo()
Bom = env['mrp.bom'].sudo()

CATEGORIES = {
    'A': 'A. KẸT, con đã giao',
    'B': 'B. KẸT, con chưa giao',
    'C': 'C. GIAO TRÙNG',
    'D': 'D. SẮP GIAO TRÙNG',
    'E1': 'E1. con SL 0, chưa giao (dòng rỗng)',
    'E2': 'E2. combo ko move, con đã giao',
    'E3': 'E3. combo ko move, con chưa giao',
    'E4': 'E4. move combo đã huỷ, con đã giao',
    'E5': 'E5. combo đã giao, con còn chờ ảo',
    'E6': 'E6. khác',
}
SAMPLES = 5  # số dòng mẫu in cho mỗi nhóm E


def money(v):
    return f"{(v or 0.0):,.0f}".replace(",", ".")


_bom_cache = {}


def kit_bom(line):
    key = (line.product_id.id, line.company_id.id)
    if key not in _bom_cache:
        _bom_cache[key] = Bom._bom_find(line.product_id, company_id=line.company_id.id, bom_type='phantom')[line.product_id]
    return _bom_cache[key]


def is_free(line):
    return not line.display_type and abs(line.price_subtotal) < EPS


def combo_items(line):
    """Thành phần khai ở combo_product (is_combo + Combo Items) — combo chưa có BoM vẫn biết linh kiện."""
    tmpl = line.product_id.product_tmpl_id
    if 'is_combo' not in tmpl._fields or not tmpl.is_combo:
        return env['product.product']
    return tmpl.combo_product_id.product_id


def children_from_components(line, components):
    return (line.order_id.order_line - line).filtered(lambda l: is_free(l) and l.product_id in components)


def children_by_position(line):
    """Combo chưa có BoM: các dòng thành tiền 0 liền SAU dòng combo (MISA xếp con ngay sau cha)."""
    following = line.order_id.order_line.filtered(lambda l: not l.display_type).sorted(lambda l: (l.sequence, l.id))
    after = following[list(following).index(line) + 1:]
    children = SaleLine.browse()
    for candidate in after:
        if not is_free(candidate):
            break
        children |= candidate
    return children


def categorize(line, children):
    own = line.move_ids.filtered(lambda m: m.product_id == line.product_id)
    exploded = line.move_ids.filtered(lambda m: m.product_id != line.product_id and m.state != 'cancel')
    children_done = all(c.qty_delivered >= c.product_uom_qty - EPS for c in children)
    children_moving = children.move_ids.filtered(lambda m: m.state != 'cancel')
    if own.filtered(lambda m: m.state not in OPEN):
        return 'A' if children_done else 'B'
    if exploded.filtered(lambda m: m.state == 'done') and children.filtered(lambda c: c.qty_delivered > EPS):
        return 'C'
    if exploded.filtered(lambda m: m.state not in OPEN) and children_moving:
        return 'D'
    return 'E' + rest_kind(line, children, own, exploded)


def rest_kind(line, children, own, exploded):
    """Tách nhóm E cho biết vô hại hay không."""
    delivered_children = children.filtered(lambda c: c.qty_delivered > EPS)
    if not children.filtered(lambda c: c.product_uom_qty > EPS or c.qty_delivered > EPS):
        return '1'  # dòng con SL 0, chưa giao — dòng rỗng, vô hại
    if not line.move_ids:
        return '2' if delivered_children else '3'  # dòng combo không sinh move (không phải hàng kho?)
    if own and not own.filtered(lambda m: m.state != 'cancel') and delivered_children:
        return '4'  # move mã combo đã huỷ, hàng đi qua dòng con
    if exploded.filtered(lambda m: m.state == 'done') and not delivered_children:
        return '5'  # combo nổ BoM và giao, dòng con có SL mà chưa giao — còn "chờ giao" ảo
    return '6'


def stuck_pickings(line):
    moves = line.move_ids.filtered(lambda m: m.product_id == line.product_id and m.state not in OPEN)
    return ', '.join(f"{p.name}({p.state})" for p in moves.picking_id) or '-'


def state_summary(moves):
    """'done 3, cancel 1 [KBC/OUT/1(done), ...]' — đếm theo trạng thái + phiếu, '-' nếu không có move."""
    if not moves:
        return '-'
    counts = defaultdict(int)
    for move in moves:
        counts[move.state] += 1
    pickings = ', '.join(f"{p.name}({p.state})" for p in moves.picking_id.sorted('id'))
    return f"{', '.join(f'{k} {v}' for k, v in sorted(counts.items()))} [{pickings or 'không phiếu'}]"


FIX_HINT = {
    'A': 'gộp được: bin/fix_kit_children_merge.py',
    'E2': 'gộp được: bin/fix_kit_children_merge.py',
    'E4': 'gộp được: bin/fix_kit_children_merge.py',
    'C': 'GIAO TRÙNG? xem phiếu: bin/check_so_picking_link_lost.py',
    'D': 'chặn trước khi kho giao trùng',
}


def print_detail(line, children, key):
    bom = kit_bom(line)
    own = line.move_ids.filtered(lambda m: m.product_id == line.product_id)
    exploded = line.move_ids - own
    if bom:
        bom_info = f"BoM {bom.id} tạo {str(bom.create_date)[:10]}"
    else:
        items = combo_items(line)
        bom_info = f"CHƯA có BoM, Combo Items: {', '.join(items.mapped('default_code')) or 'không khai'}"

    print(f"      combo tạo {str(line.create_date)[:10]} | {bom_info} | move mã combo: {state_summary(own)}")
    print(f"      move linh kiện của dòng combo: {state_summary(exploded)}")
    print(f"      move dòng con: {state_summary(children.move_ids)}")
    hint = FIX_HINT.get(key, 'chưa có cách sửa tự động — xem tay')
    if hint.startswith('gộp được') and not bom and not combo_items(line):
        hint = 'gộp được SAU KHI tạo BoM tay cho combo (chưa có BoM lẫn Combo Items)'
    print(f"      → {CATEGORIES[key]} | {hint}")


def children_label(children):
    label = ' + '.join(f"{c.product_id.default_code or c.product_id.name[:15]} {c.qty_delivered:g}/{c.product_uom_qty:g}"
                       for c in children)
    if children.filtered(lambda c: c.product_uom_qty < EPS and c.qty_delivered > EPS):
        label += ' [con SL 0 mà có giao]'
    return label


kit_tmpl_ids = Bom.search([('type', '=', 'phantom')]).product_tmpl_id.ids
# Combo nhận diện bằng: có Kit BoM, HOẶC mã bắt đầu 'CB', HOẶC tên bắt đầu 'Combo' (DHSPMI000053: combo
# không mã, không BoM), HOẶC khai is_combo ở combo_product.
combo_match = [('product_id.product_tmpl_id', 'in', kit_tmpl_ids), ('product_id.default_code', '=ilike', 'cb%'),
               ('product_id.name', '=ilike', 'combo%')]
if 'is_combo' in env['product.template']._fields:
    combo_match.append(('product_id.product_tmpl_id.is_combo', '=', True))
combo_domain = [('state', '=', 'sale'), ('display_type', '=', False)] + ['|'] * (len(combo_match) - 1) + combo_match
if ORDERS:
    combo_domain.append(('order_id.name', 'in', ORDERS))
combo_lines = SaleLine.search(combo_domain)

rows = defaultdict(list)
for line in combo_lines:
    bom, items = kit_bom(line), combo_items(line)
    if bom:
        children, how = children_from_components(line, bom.bom_line_ids.product_id), 'bom'
    elif items:
        children, how = children_from_components(line, items), 'items'
    else:
        children, how = children_by_position(line), 'guess'
    if not children:
        continue
    rows[categorize(line, children)].append((line, children, how))

print(f"\n{SEP}\n  COMBO XỔ DÒNG CON TRÊN ĐƠN — soát {len(combo_lines)} dòng combo của đơn đã xác nhận\n{SEP}")
for key, title in CATEGORIES.items():
    found = rows[key]
    amount = sum(r[0].price_subtotal for r in found)
    print(f"  {title:<40} {len(found):>5} dòng | {len({r[0].order_id.id for r in found}):>5} đơn | "
          f"tiền dòng combo {money(amount):>15} đ")

by_month = defaultdict(int)
for key in 'ABCD':
    for line, _children, _how in rows[key]:
        by_month[str(line.order_id.date_order)[:7]] += 1
print("\n  Theo tháng đặt đơn (A–D): " + ' | '.join(f"{m}: {n}" for m, n in sorted(by_month.items())))


HOW_NOTE = {'bom': '', 'items': ' (chưa có BoM — con theo Combo Items)', 'guess': ' (ĐOÁN — chưa có BoM lẫn Combo Items)'}


def print_row(line, children, how):
    guess = HOW_NOTE[how]
    print(f"  {line.order_id.name:<20} {str(line.order_id.date_order)[:10]} {line.product_id.default_code}"
          f" x{line.product_uom_qty:g} ĐG {line.qty_delivered:g} | con: {children_label(children)}{guess}"
          f" | treo: {stuck_pickings(line)}")


def print_orders_detail():
    """Chế độ ORDERS: in hết, kèm chi tiết — và báo đơn nào không thấy combo có dòng con."""
    by_order = defaultdict(list)
    for key, found in rows.items():
        for row in found:
            by_order[row[0].order_id.name].append((key, row))
    orders = env['sale.order'].sudo().search([('name', 'in', ORDERS)])
    for name in ORDERS:
        order = orders.filtered(lambda o: o.name == name)
        print(f"\n  ▸ {name}", end='')
        if not order:
            print(" — KHÔNG THẤY ĐƠN")
            continue
        print(f" | {order.state} | {str(order.date_order)[:10]} | {order.partner_id.display_name}")
        if not by_order.get(name):
            combos = order.order_line.filtered(lambda l: l.product_id and (kit_bom(l) or combo_items(l)))
            print(f"      không thấy combo có dòng con giá 0 (đơn phải ở trạng thái sale) | dòng kit trên đơn: "
                  f"{', '.join(f'{l.product_id.default_code} {l.qty_delivered:g}/{l.product_uom_qty:g}' for l in combos) or 'không có'}")
        for key, row in by_order.get(name, []):
            print_row(*row)
            print_detail(row[0], row[1], key)


if ORDERS:
    print_orders_detail()
else:
    for key, title in CATEGORIES.items():
        found = sorted(rows[key], key=lambda r: r[0].order_id.date_order, reverse=True)
        if not found:
            continue
        limit = SAMPLES if key.startswith('E') else LIST_LIMIT
        print(f"\n{SEP}\n  {title} — {len(found)} dòng (in {min(limit, len(found))}, mới nhất trước)\n{SEP}")
        for row in found[:limit]:
            print_row(*row)

env.cr.rollback()
print(f"\n{SEP}\n  CHỈ ĐỌC — không ghi gì.\n{SEP}")
