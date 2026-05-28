#!/usr/bin/env python3
"""
Chạy trên Odoo SH bằng lệnh:
  python odoo-bin shell -d <DATABASE> < bin/debug_forecast_vs_odoo.py
Hoặc paste thẳng vào odoo shell.

Mục đích:
  1. So sánh dự báo Odoo core vs logic custom
  2. Liệt kê toàn bộ stock.move ảnh hưởng đến dự báo
  3. Kiểm tra đơn bán (sale_id, sale_line_id) trên phiếu xuất
  4. Kiểm tra origin trên phiếu nhập
"""

PRODUCT_SEARCH = "STHT37191"   # Tìm theo default_code hoặc name

# ─────────────────────────────────────────────────────────────
env = env  # noqa – biến env đã có sẵn trong odoo shell

# Tìm sản phẩm
products = env['product.product'].sudo().search([
    '|', '|',
    ('default_code', 'ilike', PRODUCT_SEARCH),
    ('name',         'ilike', PRODUCT_SEARCH),
    ('barcode',      '=',     PRODUCT_SEARCH),
], limit=10)

if not products:
    print(f"[ERROR] Không tìm thấy sản phẩm với từ khóa '{PRODUCT_SEARCH}'")
    sys.exit(1)

# Nếu có nhiều, lấy cái đầu
product = products[0]
pid     = product.id
print("=" * 70)
print(f"SẢN PHẨM : {product.display_name}")
print(f"ID        : {pid}  |  default_code: {product.default_code}")
print("=" * 70)

# ── 1. ODOO CORE FORECAST ───────────────────────────────────
qty_available = product.qty_available
virtual_avail  = product.virtual_available   # = odoo core forecast
print(f"\n[Odoo core]")
print(f"  qty_available  (tồn thực tế) : {qty_available}")
print(f"  virtual_available  (dự báo)  : {virtual_avail}")
print(f"  incoming_qty                 : {product.incoming_qty}")
print(f"  outgoing_qty                 : {product.outgoing_qty}")
print(f"  free_qty                     : {product.free_qty}")

# Check specific locations involved in PACK move
loc_pack = env['stock.location'].sudo().search([('complete_name', 'ilike', 'Khu vực đóng gói')], limit=5)
loc_out  = env['stock.location'].sudo().search([('complete_name', 'ilike', 'Đầu ra')], limit=5)
print(f"\n[Location details for PACK move]")
for loc in loc_pack:
    print(f"  PACK src: id={loc.id}  name={loc.complete_name}  usage={loc.usage}  active={loc.active}")
for loc in loc_out:
    print(f"  OUT dst:  id={loc.id}  name={loc.complete_name}  usage={loc.usage}  active={loc.active}")

# Per-warehouse virtual_available
print(f"\n[Per-warehouse virtual_available]")
all_whs_virt = env['stock.warehouse'].sudo().search([])
for wh in all_whs_virt:
    p_wh = product.with_context(warehouse=wh.id)
    print(f"  WH={wh.name:25}  qty_available={p_wh.qty_available:6}  incoming={p_wh.incoming_qty:6}  outgoing={p_wh.outgoing_qty:6}  virtual={p_wh.virtual_available:6}")

# ── 2. STOCK.QUANT (tồn thực tế thô) ──────────────────────
quants = env['stock.quant'].sudo().search([
    ('product_id', '=', pid),
    ('location_id.usage', '=', 'internal'),
])
qty_hand_raw = sum(q.quantity for q in quants)
print(f"\n[stock.quant internal]  tổng quantity = {qty_hand_raw}")
for q in quants:
    print(f"  {q.location_id.complete_name:50s}  qty={q.quantity:8.2f}  reserved={q.reserved_quantity:8.2f}")

# ── 3. TẤT CẢ STOCK.MOVE CHƯA DONE/CANCEL (ảnh hưởng dự báo) ──
ACTIVE_STATES = ['waiting', 'confirmed', 'assigned', 'partially_available']
moves = env['stock.move'].sudo().search([
    ('product_id', '=', pid),
    ('state', 'in', ACTIVE_STATES),
])
print(f"\n[stock.move active ({len(moves)} dòng)]")
print(f"  {'ID':>7}  {'state':12}  {'src_usage':12}  {'dst_usage':12}  {'qty':>8}  {'picking':20}  {'sale?':6}  {'po?':6}  {'origin'}")
for m in moves.sorted('id'):
    src_usage = m.location_id.usage      if m.location_id      else '?'
    dst_usage = m.location_dest_id.usage if m.location_dest_id else '?'
    picking   = m.picking_id.name        if m.picking_id        else '(no picking)'
    has_sale  = 'YES' if m.sale_line_id or (m.picking_id and m.picking_id.sale_id) else 'no'
    has_po    = 'YES' if m.purchase_line_id or (m.picking_id and m.picking_id.purchase_id) else 'no'
    origin    = m.picking_id.origin if m.picking_id else (m.origin or '')
    print(f"  {m.id:>7}  {m.state:12}  {src_usage:12}  {dst_usage:12}  {m.product_uom_qty:>8.2f}  {picking:20}  {has_sale:6}  {has_po:6}  {origin}")

# ── 4. BREAKDOWN: incoming vs outgoing ─────────────────────
in_moves  = [m for m in moves if m.location_dest_id.usage == 'internal' and m.location_id.usage not in ('internal',)]
out_moves = [m for m in moves if m.location_dest_id.usage == 'customer']
out_int   = [m for m in moves if m.location_dest_id.usage == 'internal' and m.location_id.usage == 'internal']

print(f"\n[Breakdown moves]")
print(f"  Nhập vào internal (khác internal): {sum(m.product_uom_qty for m in in_moves):>8.2f}  ({len(in_moves)} move)")
print(f"  Xuất ra customer               :  {sum(m.product_uom_qty for m in out_moves):>8.2f}  ({len(out_moves)} move)")
print(f"  Internal transfers              :  {sum(m.product_uom_qty for m in out_int):>8.2f}  ({len(out_int)} move) ← không tính vào dự báo thường")

my_forecast = qty_hand_raw + sum(m.product_uom_qty for m in in_moves) - sum(m.product_uom_qty for m in out_moves)
print(f"\n[Custom logic]  {qty_hand_raw} + {sum(m.product_uom_qty for m in in_moves)} - {sum(m.product_uom_qty for m in out_moves)} = {my_forecast}")
print(f"[Odoo core]     {virtual_avail}")
print(f"[Chênh lệch]    {my_forecast - virtual_avail}")

# ── 5. PHIẾU NHẬP TỪ ĐMH ──────────────────────────────────
print(f"\n[Phiếu NHẬP từ ĐMH – state in {ACTIVE_STATES}]")
inc_domain = [
    ('product_id', '=', pid),
    ('state', 'in', ACTIVE_STATES),
    ('picking_type_id.code', '=', 'incoming'),
    '|', ('purchase_line_id', '!=', False), ('picking_id.purchase_id', '!=', False),
]
inc_moves = env['stock.move'].sudo().search(inc_domain)
inc_by_picking = {}
for m in inc_moves:
    pk = m.picking_id
    if not pk: continue
    if pk.id not in inc_by_picking:
        po = pk.purchase_id
        inc_by_picking[pk.id] = {
            'picking': pk.name,
            'state':   pk.state,
            'origin':  pk.origin or '',
            'po':      po.name if po else '—',
            'partner': (po.partner_id.name if po and po.partner_id else '') or (pk.partner_id.name if pk.partner_id else ''),
            'misa_date':   str(getattr(po, 'x_studio_misa_date', '') or ''),
            'date_planned': str(getattr(po, 'date_planned', '') or ''),
            'qty': 0,
        }
    inc_by_picking[pk.id]['qty'] += m.product_uom_qty

for v in sorted(inc_by_picking.values(), key=lambda x: x['picking']):
    print(f"  {v['picking']:20}  state={v['state']:10}  origin={v['origin']:20}  PO={v['po']:15}  "
          f"NCC={v['partner']:30}  misa={v['misa_date']:12}  planned={v['date_planned']:12}  qty={v['qty']:.0f}")

# ── 6. ODOO INTERNAL BREAKDOWN (_product_available) ────────────
print(f"\n[Kho hàng & lot_stock_id]")
all_whs = env['stock.warehouse'].sudo().search([])
for wh in all_whs:
    ls = wh.lot_stock_id
    vl = wh.view_location_id
    print(f"  WH={wh.name:20}  lot_stock={ls.complete_name:40}  id={ls.id}  view={vl.complete_name:40}  view_id={vl.id}")

print(f"\n[child_of lot_stock_id per kho]")
for wh in all_whs:
    ls = wh.lot_stock_id
    inner = env['stock.location'].sudo().search([('id', 'child_of', ls.id)]).ids
    print(f"  WH={wh.name:20}  lot_stock_id={ls.id}  children_count={len(inner)}")
    print(f"    children: {[env['stock.location'].browse(i).complete_name for i in inner[:10]]}")

# Lấy location của move 154243 (PACK move) và kiểm tra
print(f"\n[Kiểm tra move linked to SO: src location child_of lot_stock?]")
sale_mvs_all = env['stock.move'].sudo().search([
    ('product_id', '=', pid),
    ('state', 'in', ACTIVE_STATES),
    '|', ('sale_line_id', '!=', False), ('picking_id.sale_id', '!=', False),
])
for m in sale_mvs_all:
    for wh in all_whs:
        ls = wh.lot_stock_id
        inner_ids = set(env['stock.location'].sudo().search([('id', 'child_of', ls.id)]).ids)
        src_in  = m.location_id.id in inner_ids
        dst_in  = m.location_dest_id.id in inner_ids
        print(f"  move {m.id}  src={m.location_id.complete_name:40}  src_in_lot_stock={src_in}  dst_in_lot_stock={dst_in}  WH={wh.name}")

# Thử đúng domain mà controller dùng
print(f"\n[Test domain controller – SO moves FROM lot_stock children]")
for wh in all_whs:
    ls = wh.lot_stock_id
    d = [
        ('product_id', '=', pid),
        ('state', 'in', ACTIVE_STATES),
        '|', ('sale_line_id', '!=', False), ('picking_id.sale_id', '!=', False),
        ('location_id', 'child_of', ls.id),
    ]
    found = env['stock.move'].sudo().search(d)
    print(f"  WH={wh.name:20}  lot_stock={ls.complete_name}  → {len(found)} moves")

all_moves_any = env['stock.move'].sudo().search([
    ('product_id', '=', pid),
    ('state', 'not in', ['done', 'cancel']),
])
print(f"  Tổng: {len(all_moves_any)} move")
print(f"  {'ID':>7}  {'state':20}  {'src_usage':12}  {'dst_usage':12}  {'qty':>8}  {'picking':20}  {'sale?':5}  {'po?':5}  {'origin'}")
for m in all_moves_any.sorted('id'):
    src_usage = m.location_id.usage      if m.location_id      else '?'
    dst_usage = m.location_dest_id.usage if m.location_dest_id else '?'
    picking   = m.picking_id.name        if m.picking_id        else '(no picking)'
    has_sale  = 'YES' if m.sale_line_id or (m.picking_id and m.picking_id.sale_id) else 'no'
    has_po    = 'YES' if m.purchase_line_id or (m.picking_id and m.picking_id.purchase_id) else 'no'
    origin    = m.picking_id.origin if m.picking_id else (m.origin or '')
    src_name  = m.location_id.complete_name if m.location_id else '?'
    dst_name  = m.location_dest_id.complete_name if m.location_dest_id else '?'
    print(f"  {m.id:>7}  {m.state:20}  {src_usage:12}  {dst_usage:12}  {m.product_uom_qty:>8.2f}  {picking:20}  {has_sale:5}  {has_po:5}  {origin}")
    print(f"          src={src_name}")
    print(f"          dst={dst_name}")

# ── 8. PHIẾU XUẤT ĐẾN CUSTOMER (BẤT KỲ NGUỒN GỐC) ──────────
print(f"\n[Tất cả moves → customer – state in {ACTIVE_STATES}]")
all_out = env['stock.move'].sudo().search([
    ('product_id', '=', pid),
    ('state', 'in', ACTIVE_STATES),
    ('location_dest_id.usage', '=', 'customer'),
])
print(f"  Tổng: {len(all_out)} move")
for m in all_out.sorted('id'):
    pk  = m.picking_id
    so  = pk.sale_id   if pk else None
    has = 'sale_line_id=' + str(bool(m.sale_line_id)) + '  picking.sale_id=' + str(bool(so))
    print(f"  move {m.id}  {m.state:12}  qty={m.product_uom_qty:.0f}  picking={pk.name if pk else '—':20}  {has}  origin={pk.origin if pk else ''}")

# ── 9. PHIẾU XUẤT TỪ ĐBH (move gắn SO, mọi dest) ────────────
print(f"\n[Moves gắn SO (sale_line_id OR picking.sale_id) – state in {ACTIVE_STATES}]")
sale_moves = env['stock.move'].sudo().search([
    ('product_id', '=', pid),
    ('state', 'in', ACTIVE_STATES),
    '|', ('sale_line_id', '!=', False), ('picking_id.sale_id', '!=', False),
])
print(f"  Tổng: {len(sale_moves)} move")
for m in sale_moves.sorted('id'):
    pk = m.picking_id
    so = pk.sale_id if pk else None
    print(f"  move {m.id}  {m.state:12}  {m.location_id.usage:10}→{m.location_dest_id.usage:10}  qty={m.product_uom_qty:.0f}  picking={pk.name if pk else '—':20}  SO={so.name if so else '—'}")
    print(f"    src={m.location_id.complete_name}")
    print(f"    dst={m.location_dest_id.complete_name}")

if not all_out:
    # Kiểm tra rộng hơn: sales order confirmed có product này không?
    print(f"\n  → Không có move → customer. Kiểm tra sale.order.line:")
    sol = env['sale.order.line'].sudo().search([
        ('product_id', '=', pid),
        ('order_id.state', 'in', ['sale', 'done']),
    ], limit=20)
    for line in sol:
        so = line.order_id
        all_mvs = line.move_ids
        print(f"    SO={so.name:15}  state={so.state}  qty={line.product_uom_qty}")
        for mv in all_mvs:
            print(f"      move {mv.id}  state={mv.state:20}  {mv.location_id.usage:10}→{mv.location_dest_id.usage:10}  qty={mv.product_uom_qty}  picking={mv.picking_id.name if mv.picking_id else '—'}")

# ── 10. PHIẾU XUẤT TỪ ĐBH (custom filter hiện tại) ──────────
print(f"\n[Phiếu XUẤT từ ĐBH – custom domain (location_dest=customer + sale link)]")
out_domain = [
    ('product_id', '=', pid),
    ('state', 'in', ACTIVE_STATES),
    ('location_dest_id.usage', '=', 'customer'),
    '|', ('sale_line_id', '!=', False), ('picking_id.sale_id', '!=', False),
]
out_moves2 = env['stock.move'].sudo().search(out_domain)
print(f"  Tổng: {len(out_moves2)} move")
out_by_picking = {}
for m in out_moves2:
    pk = m.picking_id
    if not pk: continue
    if pk.id not in out_by_picking:
        so = pk.sale_id
        out_by_picking[pk.id] = {
            'picking': pk.name,
            'state':   pk.state,
            'origin':  pk.origin or '',
            'so':      so.name if so else '—',
            'partner': (so.partner_id.name if so and so.partner_id else '') or (pk.partner_id.name if pk.partner_id else ''),
            'qty': 0,
        }
    out_by_picking[pk.id]['qty'] += m.product_uom_qty

for v in sorted(out_by_picking.values(), key=lambda x: x['picking']):
    print(f"  {v['picking']:20}  state={v['state']:10}  origin={v['origin']:20}  SO={v['so']:15}  KH={v['partner']:30}  qty={v['qty']:.0f}")

print("\n" + "=" * 70)
print("DONE")
