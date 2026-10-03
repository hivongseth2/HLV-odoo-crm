# -*- coding: utf-8 -*-
"""
fix_kit_children_merge.py
=========================
Gộp dòng con về dòng combo cho đơn mà combo bị "xổ" thành dòng con trên đơn (nhóm A / E2 / E4 của
bin/check_kit_children_lines.py: move mã combo đang treo, hoặc dòng combo không có move / move đã huỷ —
vd DH125524949224516 sau "Đồng bộ (xoá & tạo lại)": combo x8 Đã giao 0, dòng con 8/16/8 đã giao). Case thật DH125524949234781: dòng combo
CB-M18ONEFHIWF1-2.M18FB8-M12-18FC (15.090.000 đ, SL 1, Đã giao 0, move mã combo treo ở
KBC/PICK/10754) + 3 dòng con giá 0 (M18 ONEFHIWF1-0X0 1, M18 FB8 2, M12-18FC 1) đã giao đủ qua
KBC/PICK → PACK → OUT.

Vì sao không chỉ huỷ move treo: combo nay đã có BoM, sale_mrp._get_qty_procurement chỉ đếm move LINH
KIỆN có bom_line_id của dòng combo → dòng combo tính 0 bộ đã đặt kho → lần tới có gì gọi
_action_launch_stock_rule (sửa SL, đồng bộ lại đơn) Odoo nổ BoM tạo phiếu xuất linh kiện LẦN NỮA.
Còn dòng combo "Đã giao 0" thì báo cáo/điều phối vẫn thấy chờ giao 15tr.

Cách sửa, từng dòng combo (savepoint — bỏ qua / lệch / lỗi là hoàn tác cả dòng):
  0a. Combo loại DỊCH VỤ/COMBO (Đã giao nhập tay, không sinh move — vd DHSPMI000053): dòng con giao đủ
      thì chỉ đặt Đã giao dòng combo = SL, không đụng move, không tạo BoM (các bước dưới bỏ qua).
      Combo nay là HÀNG HOÁ mà dòng còn 'manual' (tạo lúc combo là dịch vụ, vd DHSPMI000388) → tính lại
      qty_delivered_method về 'stock_move' rồi gộp như thường — chỉ nhập tay thì vẫn còn bẫy nổ BoM.
  0b. Combo hàng hoá chưa có BoM mà có Combo Items (combo_product) → tạo Kit BoM LƯU TRỮ từ đó
      (CREATE_MISSING_BOM='archived'): đủ để tính Đã giao, không đổi giá combo, không đổi đơn bán sau.
  1. Huỷ move CHƯA XONG của chính mã combo (cả chuỗi), nếu có.
  2. Mọi move chưa huỷ của dòng con → sale_line_id = dòng combo, bom_line_id = dòng BoM cùng sản phẩm.
     Hàng không đi lại, tồn kho không đổi — chỉ đổi move đó "thuộc" dòng nào.
  3. Tính lại Đã giao (dòng con về 0 — Odoo cấm hạ SL dưới Đã giao), rồi dòng con → SL 0 (context
     skip_procurement để Odoo không đặt kho bù; Odoo tự ghi chú đổi SL lên đơn). Đúng thứ đồng bộ MISA bản
     hiện tại cũng sẽ làm: combo có BoM thì bỏ dòng con, dòng CRM không còn → SL 0.
  4. Kiểm: dòng combo Đã giao = SL đặt và đặt kho đủ (_get_qty_procurement = SL); dòng con Đã giao 0.
     Đặt kho DƯ vì chuỗi PICK → PACK đứt (PACK huỷ rồi tạo lại không nối, vd DH125524949225123) → nối lại
     đúng cặp move rồi kiểm lại (relink_broken_chains, soát bằng bin/check_kit_procurement_count.py).
     Đặt kho THIẾU vì move tới khách có đích cuối (location_final_id) trống (vd DH125524949224365) → điền
     đích cuối = nơi move đã tới rồi kiểm lại (fill_missing_final_location).
Gộp BÙ: combo đã nổ BoM một phần (vd S05422: máy + pin theo BoM combo, sạc theo dòng bổ sung) → chỉ gộp
linh kiện còn thiếu; mỗi linh kiện cộng phần theo combo + theo dòng con phải đủ định mức, đi cả hai đường
thì bỏ qua (trùng thật). Mã thay thế (SUBSTITUTES, vd DCB184 → DCB184-B1) được tính là linh kiện đó.
Đơn có NHIỀU combo dùng chung linh kiện (vd 3 combo M12 cùng M12B4 + C12C): dòng con lấy theo VỊ TRÍ (khối
giá 0 ngay sau từng combo, đúng cách MISA xếp) thay vì theo sản phẩm; khối lệch định mức thì vẫn bỏ qua.
Bỏ qua nếu: đơn khoá; dòng con không nằm ngay sau combo khi có combo dùng chung; linh kiện đi cả theo combo
lẫn dòng con (trùng); dòng combo còn move linh kiện chưa xong; mã combo
đã có move XONG; move treo đang giữ hàng;
dòng con còn move CHƯA XONG; SL giao từng linh kiện ≠ định mức BoM × SL combo; con đã xuất hoá đơn.

ORDERS: đơn cần sửa; để [] = quét mọi dòng combo (có giá, chưa giao đủ) có dòng con giá 0. Log in hết
dòng SỬA / LỖI; BỎ QUA gom theo lý do, mỗi lý do vài mẫu.

DRY_RUN = True (mặc định): làm thật từng dòng để in kết quả rồi rollback ngay dòng đó. Đặt False để ghi
(commit từng dòng). MAX_LINES dòng mỗi lượt; ghi thật thì chạy lại tới khi hết ứng viên.

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/fix_kit_children_merge.py
"""

import re
from collections import defaultdict

# TRƯỜNG HỢP 2 — combo "xổ" dòng con trên đơn. Để [] = quét mọi dòng combo chưa giao đủ có dòng con giá 0.
ORDERS = []
DRY_RUN = False
# Combo hàng hoá CHƯA có BoM nhưng có Combo Items (combo_product) — không có BoM thì Odoo không quy
# move linh kiện ra số bộ, không gộp được. Chọn cách tạo BoM:
#   'archived' (mặc định): tạo Kit BoM ở trạng thái LƯU TRỮ. sale_mrp tính Đã giao theo BoM gắn trên move
#       (bom_line_id) nên lưu trữ vẫn đếm đúng; còn wordpress_sync (tính giá combo) và _bom_find (nổ BoM khi
#       bán) chỉ thấy BoM đang dùng → KHÔNG đổi giá, đơn bán SAU vẫn y như cũ.
#   'active': tạo BoM đang dùng bằng wizard hlv_combo_to_bom — wordpress_sync sẽ GHI ĐÈ giá bán combo
#       (list_price, giá web/TMĐT/thương mại) theo tổng linh kiện (chạy thử 02/10/2026: "Queued sync ...
#       48-32-4364D-5MUI"). Chỉ dùng khi đã chốt giá combo theo BoM là đúng.
#   False: không tạo, BỎ QUA.
CREATE_MISSING_BOM = 'archived'
ARCHIVED_BOM_CODE = 'BoM lưu trữ — chỉ để tính Đã giao đơn cũ (fix_kit_children_merge)'
EPS = 0.001
SEP = "=" * 100
OPEN = ('done', 'cancel')
# Mã thay thế: {mã linh kiện trong BoM: [mã thực tế đã giao thay]}. CHỈ điền khi đã xác nhận đúng cùng hàng
# — script coi hàng giao bằng mã thay thế là linh kiện đó của combo.
SUBSTITUTES = {
    'DC18RC-KH': ['195584-2'],   # DH125524949226738: BoM ghi DC18RC-KH, giao [195584-2] Sạc nhanh DC18RC
    'DCB184': ['DCB184-B1'],     # DH125524949227175: BoM ghi DCB184, dòng bổ sung giao [DCB184-B1] x2
}
SKIP_SAMPLES = 3  # mỗi lý do BỎ QUA in tối đa N đơn mẫu — muốn liệt kê hết thì tăng lên (vd 50)
MAX_LINES = 300  # mỗi lượt xử lý tối đa N dòng combo — log ngắn, RAM thấp; chạy lại để làm tiếp

SaleLine = env['sale.order.line'].sudo()
Move = env['stock.move'].sudo()


class MergeMismatch(Exception):
    """Gộp xong mà số không như kỳ vọng — để savepoint hoàn tác dòng đó."""


class Skip(Exception):
    """Bỏ qua dòng — ném ra để savepoint hoàn tác cả BoM vừa tạo (nếu có)."""


def kit_bom(line):
    return env['mrp.bom']._bom_find(line.product_id, company_id=line.company_id.id, bom_type='phantom')[line.product_id]


def combo_items(line):
    """Thành phần khai ở combo_product (is_combo + Combo Items), rỗng nếu không có / module không cài."""
    tmpl = line.product_id.product_tmpl_id
    if 'is_combo' not in tmpl._fields or not tmpl.is_combo:
        return env['product.product']
    return tmpl.combo_product_id.product_id


_substitute_cache = {}


def substitute_products(products):
    """Sản phẩm thay thế (theo SUBSTITUTES) của các linh kiện `products`."""
    codes = [sub for p in products for sub in SUBSTITUTES.get(p.default_code or '', [])]
    key = tuple(sorted(codes))
    if key not in _substitute_cache:
        _substitute_cache[key] = (env['product.product'].with_context(active_test=False).search(
            [('default_code', 'in', codes)]) if codes else env['product.product'])
    return _substitute_cache[key]


def components_of(line):
    """Linh kiện theo BoM (kèm mã thay thế), không có BoM thì theo Combo Items."""
    bom = kit_bom(line)
    base = bom.bom_line_ids.product_id if bom else combo_items(line)
    return base | substitute_products(base)


def bom_line_for(bom, product):
    """Dòng BoM ứng với sản phẩm đã giao: đúng mã, hoặc mã thay thế khai trong SUBSTITUTES."""
    exact = bom.bom_line_ids.filtered(lambda bl: bl.product_id == product)
    if exact:
        return exact[:1]
    return bom.bom_line_ids.filtered(
        lambda bl: (product.default_code or '') in SUBSTITUTES.get(bl.product_id.default_code or '', []))[:1]


def archived_bom(line):
    """BoM lưu trữ script đã tạo cho combo này ở dòng trước (dùng lại, không tạo trùng)."""
    return env['mrp.bom'].sudo().with_context(active_test=False).search([
        ('product_tmpl_id', '=', line.product_id.product_tmpl_id.id), ('type', '=', 'phantom'),
        ('active', '=', False), ('code', '=', ARCHIVED_BOM_CODE)], limit=1)


def create_archived_bom(line):
    """Kit BoM LƯU TRỮ từ Combo Items. Tự tạo thay vì gọi wizard hlv_combo_to_bom vì wizard chỉ tạo BoM
    đang dùng — tạo xong mới lưu trữ thì giá combo đã bị wordpress_sync ghi đè lúc BoM còn hoạt động."""
    tmpl = line.product_id.product_tmpl_id
    items = tmpl.combo_product_id
    return env['mrp.bom'].sudo().with_context(active_test=False).create({
        'product_tmpl_id': tmpl.id,
        'type': 'phantom',
        'product_qty': 1.0,
        # Phải ghi ĐVT của sản phẩm: bỏ trống thì mrp.bom lấy mặc định uom.product_uom_unit (ở đây là
        # "Cái" #1, nhóm STOPUSED) — khác nhóm với "Cái" #35 (nhóm Unit) trên dòng CB-48-32-4364D-1MUI →
        # sale_mrp quy đổi ĐVT dòng → ĐVT BoM thì lỗi "doesn't belong to the same category".
        'product_uom_id': tmpl.uom_id.id,
        'active': False,
        'code': ARCHIVED_BOM_CODE,
        'bom_line_ids': [(0, 0, {
            'product_id': item.product_id.id,
            'product_qty': item.product_quantity,
            'product_uom_id': item.product_id.uom_id.id,
        }) for item in items],
    })


def create_bom_from_combo(line):
    """Tạo Kit BoM đang dùng từ Combo Items bằng wizard hlv_combo_to_bom (không đổi loại sản phẩm)."""
    if 'combo.to.bom.wizard' not in env:
        raise Skip("combo chưa có BoM và module hlv_combo_to_bom không cài")
    # active_test=False: combo đã lưu trữ thì Many2many của wizard đọc ra rỗng → "Vui lòng chọn ít nhất
    # một sản phẩm Combo" (gặp ở CB-48-32-4364D-1MUI). skip_wordpress_sync: không xếp hàng đẩy giá lên web.
    env['combo.to.bom.wizard'].sudo().with_context(active_test=False, skip_wordpress_sync=True).create({
        'product_template_ids': [(6, 0, line.product_id.product_tmpl_id.ids)],
        'bom_type': 'phantom',
        'convert_product_type': False,
    }).action_convert()
    bom = kit_bom(line)
    if not bom:
        raise MergeMismatch("wizard combo→BoM không tạo được BoM")
    return bom


def children_of(line, components):
    return (line.order_id.order_line - line).filtered(
        lambda l: not l.display_type and abs(l.price_subtotal) < EPS and l.product_id in components)


def children_by_position(line):
    """Combo không BoM, không Combo Items: các dòng thành tiền 0 liền SAU dòng combo (MISA xếp con sau cha)."""
    ordered = line.order_id.order_line.filtered(lambda l: not l.display_type).sorted(lambda l: (l.sequence, l.id))
    children = SaleLine.browse()
    for candidate in ordered[list(ordered).index(line) + 1:]:
        if abs(candidate.price_subtotal) >= EPS:
            break
        children |= candidate
    return children


def looks_like_combo(line):
    """Chỉ nhánh nhập tay mới cần — tránh đánh dấu đã giao cho dòng dịch vụ thường (phí ship + quà 0đ)."""
    product = line.product_id
    return bool(kit_bom(line) or combo_items(line)
                or (product.default_code or '').lower().startswith('cb')
                or (product.name or '').lower().startswith('combo'))


def manual_children(line):
    """Dòng con của combo loại dịch vụ/combo: theo BoM / Combo Items nếu có, không thì theo vị trí."""
    components = components_of(line) or combo_items(line)
    return children_of(line, components) if components else children_by_position(line)


def mark_manual_delivered(line):
    """Combo loại dịch vụ/combo (Đã giao nhập tay, không sinh move): hàng đi qua dòng con giá 0 → khi dòng
    con giao đủ thì đặt Đã giao dòng combo = SL. Không đụng move, không tạo BoM — dòng dịch vụ không bao
    giờ đặt kho nên không có bẫy nổ BoM lần hai."""
    children = manual_children(line)
    if not children:
        raise Skip(f"combo loại {line.product_id.type} nhưng không thấy dòng con giá 0")
    short = children.filtered(lambda c: c.product_uom_qty < EPS or c.qty_delivered < c.product_uom_qty - EPS)
    if short:
        raise Skip("dòng con chưa giao đủ: " + ', '.join(
            f"{c.product_id.default_code or c.product_id.name[:15]} {c.qty_delivered:g}/{c.product_uom_qty:g}" for c in short))
    before = line.qty_delivered
    line.write({'qty_delivered': line.product_uom_qty})
    if abs(line.qty_delivered - line.product_uom_qty) >= EPS:
        raise MergeMismatch(f"ghi Đã giao xong mà vẫn {line.qty_delivered:g}")
    return 'SỬA', (f"combo loại {line.product_id.type} (Đã giao nhập tay): Đã giao {before:g} → {line.qty_delivered:g} | "
                   f"dòng con đã giao đủ: {', '.join(children.product_id.mapped(lambda p: p.default_code or p.name[:15]))}")


def refresh_delivered_method(line):
    """Dòng tạo lúc combo còn là DỊCH VỤ giữ qty_delivered_method='manual' dù combo nay là hàng hoá —
    sale._compute_qty_delivered_method chỉ depends 'is_expense', đổi loại sản phẩm không tính lại. Để
    'manual' thì Đã giao không tính từ move, mà Odoo vẫn đặt kho cho dòng hàng hoá (bẫy nổ BoM lần hai)."""
    env.add_to_compute(SaleLine._fields['qty_delivered_method'], line)
    line.flush_recordset(['qty_delivered_method'])
    if line.qty_delivered_method != 'stock_move':
        raise Skip(f"dòng combo Đã giao '{line.qty_delivered_method}', tính lại vẫn không ra 'stock_move'")


def stuck_combo_moves(line):
    """Move chưa xong của CHÍNH mã combo trên dòng, kèm các bước trước/sau trong chuỗi."""
    moves = line.move_ids.filtered(lambda m: m.product_id == line.product_id and m.state not in OPEN)
    seen = Move.browse()
    while moves:
        seen |= moves
        moves = (moves.move_orig_ids | moves.move_dest_ids).filtered(
            lambda m: m.product_id == line.product_id and m.state not in OPEN) - seen
    return seen


def sibling_combos(line, components):
    """Dòng combo khác (có giá) trên cùng đơn dùng chung linh kiện với combo này."""
    return (line.order_id.order_line - line).filtered(
        lambda l: l.product_id and abs(l.price_subtotal) >= EPS and components_of(l) & components)


def children_for(line, bom):
    """(dòng con, ghi chú). Đơn có combo khác dùng chung linh kiện (vd DH125524948221363: 3 combo M12 cùng
    M12B4 + C12C) thì ghép theo SẢN PHẨM không biết dòng con nào của combo nào → lấy theo VỊ TRÍ: MISA xếp
    dòng con ngay sau dòng cha, khối giá 0 dừng ở dòng có giá kế tiếp, nên mỗi combo một khối riêng. Khối
    không đúng định mức thì skip_reason vẫn chặn (lệch định mức)."""
    components = bom.bom_line_ids.product_id | substitute_products(bom.bom_line_ids.product_id)
    siblings = sibling_combos(line, components)
    if not siblings:
        return children_of(line, components), ''
    children = children_by_position(line).filtered(lambda c: c.product_id in components)
    if not children:
        raise Skip(f"đơn còn combo khác dùng chung linh kiện ({', '.join(siblings.product_id.mapped('default_code'))}) "
                   "và dòng con không nằm ngay sau combo — không biết dòng con thuộc combo nào, xem tay")
    return children, f"chia dòng con theo vị trí (đơn có {len(siblings) + 1} combo dùng chung linh kiện) | "


def own_component_delivered(line, bom):
    """{dòng BoM: SL ròng đã tới khách} từ move linh kiện CỦA CHÍNH dòng combo (combo đã nổ BoM)."""
    own = defaultdict(float)
    for move in line.move_ids.filtered(lambda m: m.state == 'done' and m.product_id != line.product_id):
        bom_line = move.bom_line_id if move.bom_line_id in bom.bom_line_ids else bom_line_for(bom, move.product_id)
        if move.location_dest_id.usage == 'customer':
            own[bom_line] += move.product_qty
        elif move.location_id.usage == 'customer' and move.to_refund:
            own[bom_line] -= move.product_qty
    return own


def skip_reason(line, bom, children, stuck):
    own_moves = line.move_ids.filtered(lambda m: m.product_id != line.product_id and m.state != 'cancel')
    if own_moves.filtered(lambda m: m.state != 'done'):
        return "dòng combo còn move linh kiện chưa xong — đợi giao xong rồi gộp"
    if line.move_ids.filtered(lambda m: m.product_id == line.product_id and m.state == 'done'):
        return "mã combo đã có move XONG (đã xuất chính mã combo) — xử lý tay"
    if stuck.filtered(lambda m: m.quantity > 0 or m.picked):
        return "move mã combo đang giữ hàng / đã đánh dấu lấy"
    if children.move_ids.filtered(lambda m: m.state not in OPEN):
        return "dòng con còn move chưa xong — đợi giao xong rồi gộp"
    if children.filtered(lambda c: c.qty_invoiced > EPS):
        return "dòng con đã xuất hoá đơn trong Odoo"
    # Gộp BÙ: combo đã nổ BoM một phần (vd S05422: máy + pin đi theo BoM combo, sạc đi theo dòng bổ sung) →
    # mỗi linh kiện phải đủ định mức khi CỘNG phần đã đi theo combo với phần đi theo dòng con; linh kiện đi
    # theo CẢ HAI đường mới là giao trùng.
    own = own_component_delivered(line, bom)
    from_children = defaultdict(float)
    for child in children:
        from_children[bom_line_for(bom, child.product_id)] += child.qty_delivered
    for bom_line in bom.bom_line_ids:
        need = bom_line.product_qty / (bom.product_qty or 1.0) * line.product_uom_qty
        if own[bom_line] > EPS and from_children[bom_line] > EPS:
            return (f"dòng combo đã có move linh kiện (đã nổ BoM) — gộp nữa là TRÙNG, xem tay: "
                    f"{bom_line.product_id.default_code} đi cả theo combo ({own[bom_line]:g}) lẫn dòng con "
                    f"({from_children[bom_line]:g})")
        got = own[bom_line] + from_children[bom_line]
        if abs(got - need) >= EPS:
            return (f"dòng con giao lệch định mức BoM: {bom_line.product_id.default_code} giao "
                    f"{got:g} ≠ {need:g} (= {line.product_uom_qty:g} bộ)")
    return ''


def relink_broken_chains(line):
    """Nối lại chuỗi PICK → PACK bị đứt khi phiếu PACK bị huỷ rồi tạo lại không nối vào PICK.

    Case DH125524949225123: PICK move 57508 (Sau trống) và PACK/04073 move 58550 (Trước trống). Odoo chỉ
    đếm move cuối chuỗi, nên PICK bị coi là cuối một chuỗi riêng → đặt kho 2 bộ cho 1 bộ thật. Chỉ nối
    khi khớp tuyệt đối: cùng sản phẩm, cùng SL, đều XONG, A chưa có bước sau còn sống, B chưa có bước
    trước còn sống, A giao tới đúng vị trí B lấy ra, B xong sau A — và mỗi A chỉ có đúng một B.
    Chỉ đổi liên kết move, không đổi tồn kho / SL. Trả danh sách 'A→B' đã nối."""
    done = line.move_ids.filtered(lambda m: m.state == 'done' and not m.scrapped)
    heads = done.filtered(lambda m: not m.move_dest_ids.filtered(lambda d: d.state != 'cancel'))
    tails = done.filtered(lambda m: not m.move_orig_ids.filtered(lambda o: o.state != 'cancel'))
    links = []
    for head in heads.filtered(lambda m: m.location_dest_id.usage == 'internal'):
        matches = (tails - head).filtered(
            lambda m: m.product_id == head.product_id and m.location_id == head.location_dest_id
            and abs(m.quantity - head.quantity) < EPS and m.date >= head.date)
        if len(matches) != 1:
            continue
        head.write({'move_dest_ids': [(4, matches.id)]})
        links.append(f"{head.id}→{matches.id}")
    return links


def fill_missing_final_location(line):
    """Điền location_final_id cho move ĐÃ XONG giao tới khách mà đích cuối trống.

    Case DH125524949224365: move 54250 (máy M18 BLPDRC-0C0 x5, TSN/OUT/04059 → Partners/Customers) có
    location_final_id trống — sale_mrp._get_incoming_outgoing_moves_filter chỉ đếm move có đích cuối là
    khách → máy đếm 0 → đặt kho 0 bộ dù Đã giao 5/5 (Đã giao đếm theo location_dest_id nên vẫn đúng).
    Đích cuối của move đã tới khách chính là nơi nó tới; chỉ là trường thông tin, không đổi tồn kho."""
    moves = line.move_ids.filtered(
        lambda m: m.state == 'done' and m.location_dest_id.usage == 'customer' and not m.location_final_id)
    for move in moves:
        move.write({'location_final_id': move.location_dest_id.id})
    return moves


def recompute_delivered(lines):
    env.add_to_compute(SaleLine._fields['qty_delivered'], lines)
    lines.flush_recordset(['qty_delivered'])


def merge_line(line):
    """Gộp dòng con về 1 dòng combo; trả (trạng thái, ghi chú). Bỏ qua / lỗi → hoàn tác cả dòng."""
    try:
        with env.cr.savepoint():
            return _merge_line(line)
    except Skip as skip:
        return 'BỎ QUA', str(skip)
    except Exception as error:  # noqa: BLE001 — lỗi gì cũng hoàn tác dòng này, báo ra rồi đi tiếp
        return 'LỖI', f"{error} — đã hoàn tác"


def _merge_line(line):
    if line.order_id.locked:
        raise Skip("đơn đang bị khoá")
    if line.qty_delivered_method == 'manual' and line.product_id.type != 'consu':
        return mark_manual_delivered(line)
    if line.qty_delivered_method != 'stock_move':
        refresh_delivered_method(line)
    bom, created = kit_bom(line) or archived_bom(line), ''
    if not bom:
        if not combo_items(line):
            raise Skip("combo chưa có BoM, cũng không khai Combo Items — tạo BoM tay rồi chạy lại")
        if not CREATE_MISSING_BOM:
            raise Skip("combo chưa có BoM (có Combo Items) — bật CREATE_MISSING_BOM ('archived' không đổi giá)")
        bom = create_archived_bom(line) if CREATE_MISSING_BOM == 'archived' else create_bom_from_combo(line)
        kind = 'LƯU TRỮ' if not bom.active else 'đang dùng'
        created = (f"tạo BoM {kind} {bom.id} từ Combo Items "
                   f"({', '.join(bom.bom_line_ids.product_id.mapped('default_code'))}) | ")
    (children, split_note), stuck = children_for(line, bom), stuck_combo_moves(line)
    if not children:
        raise Skip("không có dòng con")
    reason = skip_reason(line, bom, children, stuck)
    if reason:
        raise Skip(reason)
    stuck_pickings = ', '.join(stuck.picking_id.mapped('name'))
    moved = Move.browse()
    if stuck:
        stuck._action_cancel()
    for child in children:
        moves = child.move_ids.filtered(lambda m: m.state != 'cancel')
        moves.write({'sale_line_id': line.id, 'bom_line_id': bom_line_for(bom, child.product_id).id})
        moved |= moves
    # Tính lại TRƯỚC khi hạ SL: sale_stock._update_line_quantity cấm SL < Đã giao đang lưu.
    recompute_delivered(line | children)
    children.with_context(skip_procurement=True).write({'product_uom_qty': 0.0})
    if abs(line.qty_delivered - line.product_uom_qty) >= EPS:
        raise MergeMismatch(f"combo Đã giao {line.qty_delivered:g} ≠ {line.product_uom_qty:g}")
    # BoM lưu trữ: _get_qty_procurement dùng _bom_find (chỉ BoM đang dùng) nên không đếm được — bỏ kiểm.
    # Bẫy còn lại nhẹ hơn: nếu ai sửa SL dòng, Odoo đặt kho CHÍNH mã combo (phiếu treo), không nổ trùng.
    procured = line._get_qty_procurement() if bom.active else line.product_uom_qty
    relinked = ''
    if procured > line.product_uom_qty + EPS:
        links = relink_broken_chains(line)
        if links:
            relinked = f"nối lại {len(links)} chuỗi đứt ({', '.join(links)}) | "
            procured = line._get_qty_procurement()
    if bom.active and procured < line.product_uom_qty - EPS:
        fixed = fill_missing_final_location(line)
        if fixed:
            relinked += f"điền đích cuối cho move {', '.join(map(str, fixed.ids))} | "
            procured = line._get_qty_procurement()
    if abs(procured - line.product_uom_qty) >= EPS:
        raise MergeMismatch(f"đặt kho {procured:g} bộ ≠ {line.product_uom_qty:g} — move dòng con dư/chuỗi "
                            "move đứt, xem tay")
    if children.filtered(lambda c: c.qty_delivered > EPS):
        raise MergeMismatch("dòng con vẫn còn Đã giao > 0")
    after_pickings = ', '.join(f"{p.name}({p.state})" for p in stuck.picking_id)
    cancelled = f"huỷ move treo [{stuck_pickings} → {after_pickings}]" if stuck else "không có move treo"
    return 'SỬA', (f"{created}{split_note}{relinked}{cancelled} | chuyển {len(moved)} move của "
                   f"{len(children)} dòng con ({', '.join(children.product_id.mapped('default_code'))}) sang combo | "
                   f"combo Đã giao {line.qty_delivered:g}/{line.product_uom_qty:g}, dòng con về SL 0")


# Lọc trước bằng SQL: chỉ dòng có giá, chưa giao đủ, mà cùng đơn có dòng thành tiền 0. Nạp mọi dòng đơn
# "sale" vào ORM rồi mới lọc thì Odoo.sh giết tiến trình vì hết RAM ("Killed", 02/10/2026).
env.cr.execute("""
    SELECT sol.id
      FROM sale_order_line sol
      JOIN sale_order so ON so.id = sol.order_id
     WHERE so.state = 'sale' AND sol.display_type IS NULL
       AND abs(sol.price_subtotal) >= %(eps)s
       AND sol.qty_delivered < sol.product_uom_qty - %(eps)s
       AND (%(names)s IS NULL OR so.name = ANY(%(names)s))
       AND EXISTS (SELECT 1 FROM sale_order_line c
                    WHERE c.order_id = sol.order_id AND c.id <> sol.id
                      AND c.display_type IS NULL AND abs(c.price_subtotal) < %(eps)s)
     ORDER BY so.date_order, sol.id
""", {'eps': EPS, 'names': ORDERS or None})
candidate_ids = [r[0] for r in env.cr.fetchall()]


def is_target(line):
    return line.product_id and (
        children_of(line, components_of(line))
        or (line.qty_delivered_method == 'manual' and line.product_id.type != 'consu'
            and looks_like_combo(line) and manual_children(line)))


print(f"\n{SEP}\n  TH2 — GỘP DÒNG CON VỀ COMBO — {'CHẠY THỬ (rollback từng dòng)' if DRY_RUN else 'GHI THẬT'}: "
      f"{len(candidate_ids)} dòng ứng viên (SQL), xử lý tối đa {MAX_LINES}\n{SEP}")
counts = defaultdict(int)
skipped = defaultdict(list)  # lý do (bỏ phần sau '|') → [đơn]
processed = 0
for line_id in candidate_ids:
    if processed >= MAX_LINES:
        break
    line = SaleLine.browse(line_id)
    if not is_target(line):
        continue
    processed += 1
    order_name, label = line.order_id.name, line.product_id.default_code or line.product_id.name[:40]
    status, note = merge_line(line)
    counts[status] += 1
    if status == 'BỎ QUA':
        # Gom theo lý do: bỏ phần chi tiết sau ':' / '|' và mã trong ngoặc để cùng lý do vào một nhóm.
        reason = re.sub(r'\s*\(.*?\)', '', note.split(' | ')[0].split(':')[0])
        skipped[reason].append(f"{order_name} {label}: {note}")
    else:
        print(f"  [{status:<7}] {order_name:<20} {label}: {note}")
    # Chốt từng dòng (chạy thử: hoàn tác ngay) rồi xoá cache ORM — giữ RAM phẳng suốt cả lượt quét.
    if DRY_RUN:
        env.cr.rollback()
    else:
        env.cr.commit()
    env.invalidate_all()

if skipped:
    print(f"\n  BỎ QUA theo lý do (mỗi lý do in {SKIP_SAMPLES} mẫu):")
    for reason, rows in sorted(skipped.items(), key=lambda kv: -len(kv[1])):
        print(f"    {len(rows):>5} × {reason}")
        for row in rows[:SKIP_SAMPLES]:
            print(f"            {row}")

env.cr.rollback()
print(f"\n{SEP}\n  " + (' | '.join(f"{k}: {v}" for k, v in sorted(counts.items())) or 'Không có dòng nào'))
if processed >= MAX_LINES:
    print(f"  Dừng ở {MAX_LINES} dòng — chạy lại để làm tiếp (dòng đã sửa không còn là ứng viên).")
print("  CHẠY THỬ — đã rollback, chưa ghi gì. Đặt DRY_RUN = False rồi chạy lại." if DRY_RUN else "  XONG — đã commit.")
print(SEP)
