# -*- coding: utf-8 -*-
"""
check_studio_amount_new_formula.py
==================================
Chạy THỬ công thức mới cho field Studio x_studio_tng_tin_sau_thu (stock.picking) trên dữ liệu
thật — KHÔNG ghi gì — để xem trước khi dán vào Studio. Field này là "tiền hàng" của phiếu cho
đối soát MISA, V-Tracking (hlv_vtracking) và file xuất kế hoạch giao (hlv_sale_delivery_planning).

4 lỗi của công thức hiện tại (compute đang chạy trên server):
  1. Nhánh 2B "Vét cạn": món giá 0 KHÔNG thuộc combo nào (hàng tặng) bị gán nguyên giá 1 dòng
     combo bất kỳ trong đơn — TSN/OUT/11814 chỉ giao chai WD40 tặng mà ghi 21.449.988 đ, trong
     khi TSNSR/OUT/00018 giao combo cũng ghi 21.449.988 đ → đơn bị đếm 2 lần.
  2. Kit/combo giao NHIỀU ĐỢT: mỗi phiếu cộng NGUYÊN giá dòng kit, không theo SL giao ở phiếu.
  3. Combo tách dòng con giá 0 mà dòng cha chỉ có BOM (không is_combo): không tìm ra cha → 0 đ
     (KBC/OUT/11613, combo 16.297.200 đ).
  4. depends thiếu giá dòng đơn: sửa giá đơn bán sau khi xuất kho thì field không tính lại
     (KBC/OUT/09162, 11526).

Công thức mới (hàm new_amount bên dưới — GIỐNG HỆT đoạn code sẽ dán vào Studio):
  - Kit (move là linh kiện của dòng kit) và combo tách dòng (dòng con giá 0, dòng cha có giá
    chứa sản phẩm đó trong combo_product_id HOẶC trong BOM): giá dòng cha chia cho các phiếu
    xuất theo GIÁ TRỊ linh kiện thực giao ở từng phiếu (SL × giá niêm yết, trừ hàng trả — kể
    cả hàng nhập lại bằng Phiếu nhập kho không nối phiếu xuất), mỗi dòng cha 1 lần/phiếu.
    Tổng các phiếu luôn = giá dòng cha. Không chia theo BOM (lần chạy trước: DH125524949232981
    giao lại sau khi trả hết chỉ được 9,9/13,57 triệu; DH125524949233182 combo vừa giao kiểu
    kit vừa giao qua dòng con bị đếm 2 lần).
  - Món giá 0 không thuộc combo nào: 0 đ (bỏ "vét cạn").
  - Hàng thường / Shopee / POS: như cũ, và KHÔNG thêm giá dòng đơn vào depends (lỗi 4 không sửa
    trong công thức): lần chạy thử trước cho thấy đơn bị sửa giá SAU khi xuất HĐ thì số chụp lúc
    xuất kho mới khớp HĐ — tính theo giá hiện tại làm lệch. Giá đổi TRƯỚC khi xuất HĐ (09162,
    11526) xử lý bằng bin/fix_misa_invoice_picking_amount_from_so.py.

Script in: số phiếu đổi, với phiếu đã có HĐ thì công thức nào khớp tiền HĐ hơn, danh sách đổi
lớn nhất, và các phiếu case thật ở WATCH.

CHỈ ĐỌC — không write/create/unlink gì, không gọi MISA.

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_studio_amount_new_formula.py
"""

STUDIO_FIELD = 'x_studio_tng_tin_sau_thu'
TOLERANCE = 1000.0
BATCH = 300             # phiếu mỗi lô (xóa cache giữa các lô)
PRICE_ONLY_TOP = 15     # nhánh giá hàng thường chỉ in chừng này đơn
WATCH = ['TSN/OUT/11814', 'TSNSR/OUT/00018', 'KBC/OUT/11613', 'KBC/OUT/09162', 'KBC/OUT/09154', 'KBC/OUT/11526']
SEP = "=" * 100

Picking = env['stock.picking'].sudo()


def money(v):
    return f"{(v or 0.0):,.0f}".replace(",", ".")


def new_amount(record, flags=None):
    """Công thức mới — viết đúng kiểu Studio chấp nhận (không lambda/comprehension).
    flags (set, chỉ dùng trong script): ghi lại nhánh nào đã chạy — 'kit', 'combo', 'tặng'."""
    flags = set() if flags is None else flags
    total_inc = 0.0
    pos_order = record.pos_order_id
    moves = record.move_ids_without_package
    counted_parents = []

    for move in moves:
        line = move.sale_line_id
        qty = move.quantity
        amount_to_add = 0.0

        if line:
            parent = False

            # 1. KIT: Odoo nổ dòng kit thành move linh kiện, move vẫn trỏ về dòng kit.
            if move.bom_line_id or move.product_id.id != line.product_id.id:
                flags.add('kit')
                parent = line

            # 2. COMBO TÁCH DÒNG: dòng con giá 0, dòng cha có giá chứa đúng sản phẩm này.
            elif line.price_total == 0:
                for so_line in line.order_id.order_line:
                    if so_line.price_total <= 0:
                        continue
                    combo_ids = []
                    if so_line.product_template_id.is_combo:
                        combo_ids = so_line.product_template_id.combo_product_id.mapped('product_id').ids
                    bom_ids = so_line.product_id.bom_ids.mapped('bom_line_ids.product_id').ids
                    if move.product_id.id in combo_ids or move.product_id.id in bom_ids:
                        parent = so_line
                        break
                if parent:
                    flags.add('combo')
                else:
                    # Không thuộc combo nào = hàng tặng giá 0 → 0 đ.
                    flags.add('tặng')

            if parent:
                # Mỗi dòng cha cộng 1 lần/phiếu: giá dòng cha × phần linh kiện ở phiếu này / linh
                # kiện của MỌI phiếu xuất của dòng đó (move kit của chính dòng cha + move dòng con
                # giá 0). Không chia theo BOM: BOM đổi / linh kiện thay thế thì tỉ lệ BOM sai, và
                # 1 combo vừa giao kiểu kit vừa giao qua dòng con không bị đếm 2 lần. Phiếu khác đã
                # xong tính SL trừ hàng trả (giao lại sau khi trả hết thì phiếu mới nhận đủ tiền),
                # chưa xong tính SL yêu cầu; phần còn thiếu của chính phiếu này (sắp thành phiếu
                # chờ) cũng tính vào mẫu. Hàng khách trả nhập bằng Phiếu nhập kho KHÔNG nối phiếu
                # xuất (DH125524949229407: TSN/IN/01204 nhập lại 6 bộ của TSN/OUT/07696 rồi giao
                # lại ở TSN/OUT/12215) cũng trừ khỏi mẫu. Chia theo GIÁ TRỊ (SL × giá niêm yết
                # linh kiện), không theo số cái — pin + sạc không ăn 2/3 giá combo máy mài; mọi
                # linh kiện giá niêm yết 0 thì chia theo SL.
                if parent.id not in counted_parents:
                    counted_parents.append(parent.id)
                    component_ids = []
                    if parent.product_template_id.is_combo:
                        component_ids = parent.product_template_id.combo_product_id.mapped('product_id').ids
                    component_ids = component_ids + parent.product_id.bom_ids.mapped('bom_line_ids.product_id').ids
                    own_qty = 0.0
                    all_qty = 0.0
                    own_value = 0.0
                    all_value = 0.0
                    for so_line in parent.order_id.order_line:
                        if so_line.id != parent.id and not (
                            so_line.price_total == 0 and so_line.product_id.id in component_ids
                        ):
                            continue
                        for other in so_line.move_ids:
                            if other.state == 'cancel':
                                continue
                            unit_value = other.product_id.lst_price
                            if other.picking_code == 'incoming':
                                if other.state == 'done' and other.origin_returned_move_id.picking_code != 'outgoing':
                                    all_qty -= other.quantity
                                    all_value -= other.quantity * unit_value
                                continue
                            if other.picking_code != 'outgoing':
                                continue
                            if other.picking_id.id == record.id:
                                counted = other.quantity
                                own_qty += other.quantity
                                own_value += other.quantity * unit_value
                                if other.state != 'done' and other.product_uom_qty > other.quantity:
                                    counted = other.product_uom_qty
                            elif other.state == 'done':
                                back_qty = 0.0
                                for back in other.returned_move_ids:
                                    if back.state == 'done':
                                        back_qty += back.quantity
                                counted = max(other.quantity - back_qty, 0.0)
                            else:
                                counted = other.product_uom_qty
                            all_qty += counted
                            all_value += counted * unit_value
                    ratio = 0.0
                    if all_value > 0:
                        ratio = own_value / all_value
                    elif all_qty > 0:
                        ratio = own_qty / all_qty
                    amount_to_add = parent.price_total * min(ratio, 1.0)
            elif line.product_uom_qty:
                # 3. HÀNG THƯỜNG & SHOPEE: đơn giá thực = tổng tiền dòng (đã trừ KM) / SL đặt.
                amount_to_add = qty * line.price_total / line.product_uom_qty

        elif pos_order:
            for pos_line in pos_order.lines:
                if pos_line.product_id.id == move.product_id.id and pos_line.qty != 0:
                    amount_to_add = qty * pos_line.price_subtotal_incl / pos_line.qty
                    break

        total_inc += amount_to_add
    return total_inc


# Tiền trả tính lại theo từng tiền gộp (cũ / mới) bằng đúng hàm của module bản 1.14 — số trả đang
# lưu của bản cũ sai ở phiếu trả qua lệnh chuyển nội bộ và phiếu dòng đơn bị đổi giá (KBC/OUT/10078
# trả 35.523.360 đ > tiền gộp 13.573.440 đ).
HAS_114 = hasattr(Picking, '_misa_invoice_returned_amount_for')
if not HAS_114:
    print("⚠️ Server chưa có module bản 1.14 — dùng số trả đang lưu (có thể sai ở phiếu có hàng trả).")

picking_ids = Picking.search(Picking._misa_invoice_dashboard_base_domain()).ids
print(f"\n{SEP}\n  CHẠY THỬ CÔNG THỨC STUDIO MỚI trên {len(picking_ids)} phiếu xuất kho (không ghi gì)\n{SEP}")

# Chạy theo lô và xóa cache sau mỗi lô, chỉ giữ số liệu nhẹ — giữ nguyên recordset 6.000+ phiếu
# kèm quan hệ sâu (move → dòng đơn → đơn → BOM) làm tiến trình bị server kill vì hết bộ nhớ.
rows_by_order = {}      # order_id -> list dòng nhẹ của MỌI phiếu thuộc đơn (để in chi tiết)
order_names = {}
multi_order_rows = []   # phiếu gộp nhiều đơn có đổi — không chấm được theo đơn
watch_rows = {}
for start in range(0, len(picking_ids), BATCH):
    for picking in Picking.browse(picking_ids[start:start + BATCH]):
        old = getattr(picking, STUDIO_FIELD, 0.0) or 0.0
        flags = set()
        new = new_amount(picking, flags)
        if HAS_114:
            returned_old = picking._misa_invoice_returned_amount_for(old)
            returned_new = picking._misa_invoice_returned_amount_for(new)
        else:
            returned_old = returned_new = picking.misa_invoice_returned_amount or 0.0
        row = {
            'name': picking.name, 'date': str(picking.date_done)[:10], 'old': old, 'new': new,
            'returned_old': returned_old, 'returned_new': returned_new,
            'allocated': picking.misa_invoice_allocated_amount or 0.0,
            'flags': flags, 'changed': abs(new - old) > TOLERANCE,
        }
        if picking.name in WATCH:
            watch_rows[picking.name] = (old, new)
        orders = picking.misa_invoice_sale_order_ids
        if len(orders) == 1:
            rows_by_order.setdefault(orders.id, []).append(row)
            order_names[orders.id] = orders.name
        elif row['changed']:
            multi_order_rows.append(row)
    env.invalidate_all()

# So ở MỨC ĐƠN HÀNG: tiền HĐ quy về từng phiếu được rót theo tiền xuất kho CŨ, so từng phiếu thì
# số cũ luôn được lợi. Tổng HĐ của cả đơn thì không phụ thuộc cách chia. Chấm theo NHÁNH: nhánh
# "chỉ giá hàng thường" là nhánh sẽ KHÔNG áp dụng, cần biết riêng để chắc bỏ nó là đúng.
scores = {}
orders_by_branch = {}
for order_id, rows in rows_by_order.items():
    changed = [r for r in rows if r['changed']]
    if not changed:
        continue
    flags = set()
    for r in changed:
        flags |= r['flags']
    branch = ' + '.join(sorted(flags)) or 'chỉ giá hàng thường'
    allocated = sum(r['allocated'] for r in rows)
    old_total = sum(max(r['old'] - r['returned_old'], 0.0) for r in rows)
    new_total = sum(max(r['new'] - r['returned_new'], 0.0) for r in rows)
    verdict = 'chưa có HĐ'
    if allocated > TOLERANCE:
        score = scores.setdefault(branch, {'new': 0, 'old': 0, 'same': 0})
        old_gap, new_gap = abs(old_total - allocated), abs(new_total - allocated)
        if new_gap + TOLERANCE < old_gap:
            score['new'] += 1
            verdict = 'mới khớp HĐ hơn'
        elif old_gap + TOLERANCE < new_gap:
            score['old'] += 1
            verdict = '⚠️ cũ khớp HĐ hơn'
        else:
            score['same'] += 1
            verdict = 'như nhau'
    orders_by_branch.setdefault(branch, []).append((order_id, verdict, old_total, new_total, allocated))

changed_count = sum(1 for rows in rows_by_order.values() for r in rows if r['changed']) + len(multi_order_rows)
print(f"\n  {changed_count} phiếu đổi > {money(TOLERANCE)} đ ({len(multi_order_rows)} phiếu gộp nhiều đơn, không chấm theo đơn)")
print("  Đơn đã có HĐ có phiếu đổi — so tổng đơn với tổng HĐ, theo nhánh:")
for branch, score in sorted(scores.items()):
    print(f"    {branch:<28} mới khớp hơn {score['new']:>4} | cũ khớp hơn {score['old']:>4} | như nhau {score['same']:>4}")

print("\n  Case thật:")
for name in WATCH:
    old, new = watch_rows.get(name, (None, None))
    print(f"    {name:<16} " + ("(không trong phạm vi)" if old is None else f"cũ {money(old):>13} → mới {money(new):>13}"))

for branch in sorted(orders_by_branch, key=lambda b: b == 'chỉ giá hàng thường'):
    items = sorted(orders_by_branch[branch], key=lambda it: -abs(it[3] - it[2]))
    limit = PRICE_ONLY_TOP if branch == 'chỉ giá hàng thường' else len(items)
    print(f"\n{SEP}\n  NHÁNH {branch.upper()} — {len(items)} đơn"
          + (f" (in {limit} đơn đổi nhiều nhất)" if limit < len(items) else '') + f"\n{SEP}")
    for order_id, verdict, old_total, new_total, allocated in items[:limit]:
        print(f"\n  {order_names[order_id]} | tổng cũ {money(old_total)} → mới {money(new_total)}"
              f" | tổng HĐ {money(allocated)} | {verdict}")
        for r in rows_by_order[order_id]:
            mark = '   ⬅ đổi' if r['changed'] else ''
            print(f"      {r['name']:<16} {r['date']} cũ {money(r['old']):>13} → mới {money(r['new']):>13}"
                  f" trả {money(r['returned_old']):>11}→{money(r['returned_new']):>11} HĐ quy về {money(r['allocated']):>13}"
                  f" {', '.join(sorted(r['flags']))}{mark}")
print(f"\n{SEP}")
print("  Nhìn các nhánh kit / combo / tặng: 'mới khớp hơn' áp đảo → dán công thức mới vào Studio (giữ\n"
      "  nguyên depends), rồi CHỈ tính lại các phiếu có kit/combo/tặng. Nhánh 'chỉ giá hàng thường' là\n"
      "  phần KHÔNG áp dụng — phiếu hàng thường giữ nguyên số đã chụp.")
print(SEP)
