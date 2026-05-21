# -*- coding: utf-8 -*-
"""
debug_combo_delivery.py
=======================
Chẩn đoán tại sao combo (Combo Kit badge) hiện "Đã Giao: 0"
dù linh kiện đã được giao.

Chạy:
    python odoo-bin shell -d <DATABASE> < bin/debug_combo_delivery.py

Kiểm tra:
  A) Dòng sản phẩm của đơn hàng (is_kit, qty_delivered)
  B) Phantom BOM của các sản phẩm combo
  C) BOM lines (linh kiện) vs SOL standalone trong đơn
  D) Tính kit_fallback ratio thủ công
  E) combo.product records (nếu có)
  F) Stock moves liên kết với SOL combo cha
"""

ORDER_NAME = "DH125524949231888"

SEP  = "=" * 72
SEP2 = "-" * 60

def sec(t): print(f"\n{SEP}\n  {t}\n{SEP}")
def sub(t): print(f"\n  {SEP2}\n  {t}\n  {SEP2}")

# ─── A. Order lines ───────────────────────────────────────────────────────────
sec(f"A. ORDER LINES: {ORDER_NAME}")

so = env['sale.order'].sudo().search([('name', '=', ORDER_NAME)], limit=1)
if not so:
    print(f"  [!] Không tìm thấy đơn {ORDER_NAME}")
    raise SystemExit

print(f"  SO id={so.id}  state={so.state}  warehouse={so.warehouse_id.name}")
print(f"  {'ID':>6}  {'product_id':>6}  {'tmpl_id':>6}  {'type':8}  "
      f"{'qty_ord':>7}  {'qty_del':>7}  {'is_kit':6}  product_ref")
for l in so.order_line:
    if l.display_type:
        continue
    p = l.product_id
    tmpl = p.product_tmpl_id if p else None
    ptype = p.type if p else '?'
    has_bom = bool(env['mrp.bom'].sudo().search_count([
        ('product_tmpl_id', '=', tmpl.id), ('type', '=', 'phantom')
    ])) if tmpl else False
    print(f"  {l.id:>6}  {p.id if p else '?':>6}  {tmpl.id if tmpl else '?':>6}  "
          f"{ptype:8}  {l.product_uom_qty:>7.1f}  {l.qty_delivered:>7.1f}  "
          f"{'YES' if has_bom else 'no':6}  [{p.default_code or ''}] {p.name or '?'}")

# ─── B. Phantom BOMs cho các sản phẩm trong đơn ──────────────────────────────
sec("B. PHANTOM BOMs CỦA CÁC SẢN PHẨM TRONG ĐƠN")

all_tmpl_ids = [l.product_id.product_tmpl_id.id for l in so.order_line
                if not l.display_type and l.product_id]
kits = env['mrp.bom'].sudo().search([
    ('product_tmpl_id', 'in', all_tmpl_ids), ('type', '=', 'phantom'),
])
if not kits:
    print("  [!] Không tìm thấy phantom BOM nào cho sản phẩm trong đơn!")
else:
    for bom in kits:
        print(f"\n  BOM id={bom.id}  tmpl_id={bom.product_tmpl_id.id}"
              f"  ref=[{bom.product_tmpl_id.default_code or ''}]"
              f"  qty={bom.product_qty}")
        print(f"    {'line_id':>7}  {'prod_id':>7}  {'qty':>6}  product_ref")
        for bl in bom.bom_line_ids:
            cp = bl.product_id
            print(f"    {bl.id:>7}  {cp.id if cp else '?':>7}  {bl.product_qty:>6.2f}"
                  f"  [{cp.default_code or ''}] {cp.name or '?'}")

# ─── C. So sánh BOM lines với standalone SOLs trong đơn ──────────────────────
sec("C. SO SÁNH BOM COMPONENTS vs STANDALONE SOLs TRONG ĐƠN")

# Xây sol_by_product: product_id -> qty_delivered  (giống logic service)
sol_by_prod = {}
for l in so.order_line:
    if l.display_type or not l.product_id:
        continue
    pid = l.product_id.id
    sol_by_prod[pid] = sol_by_prod.get(pid, 0.0) + (l.qty_delivered or 0.0)

print(f"  sol_by_prod (product_id -> qty_delivered):")
for pid, qd in sorted(sol_by_prod.items()):
    p = env['product.product'].sudo().browse(pid)
    print(f"    pid={pid:>6}  qty_del={qd:>5.1f}  [{p.default_code or ''}] {p.name}")

for bom in kits:
    sub(f"BOM {bom.id} — [{bom.product_tmpl_id.default_code or ''}]")
    bom_qty = bom.product_qty or 1.0
    ratio = float('inf')
    for bl in bom.bom_line_ids:
        cp = bl.product_id
        if not cp:
            continue
        qty_per_kit = (bl.product_qty or 0.0) / bom_qty
        delivered = sol_by_prod.get(cp.id, 0.0)
        this_ratio = delivered / qty_per_kit if qty_per_kit > 0 else float('inf')
        ratio = min(ratio, this_ratio)
        match = "✓ found in SOL" if cp.id in sol_by_prod else "✗ NOT in SOL"
        print(f"  comp pid={cp.id:>6}  qty_per_kit={qty_per_kit:.2f}"
              f"  sol_delivered={delivered:.1f}  ratio={this_ratio:.2f}  {match}"
              f"  [{cp.default_code or ''}] {cp.name}")
    eff_kits = min(ratio, 1.0) if ratio != float('inf') else 0.0
    print(f"  => kit_fallback ratio={ratio:.2f}  eff_qty_del={eff_kits:.2f}")

# ─── D. Stock moves liên kết với SOL combo cha ────────────────────────────────
sec("D. STOCK MOVES LIÊN KẾT VỚI CÁC SOL (sale_line_id)")

kit_sol_ids = []
for l in so.order_line:
    if l.display_type or not l.product_id:
        continue
    tmpl = l.product_id.product_tmpl_id
    if env['mrp.bom'].sudo().search_count([
        ('product_tmpl_id', '=', tmpl.id), ('type', '=', 'phantom')
    ]):
        kit_sol_ids.append(l.id)

print(f"  Kit SOL ids: {kit_sol_ids}")
for sol_id in kit_sol_ids:
    l = env['sale.order.line'].sudo().browse(sol_id)
    moves = env['stock.move'].sudo().search([('sale_line_id', '=', sol_id)])
    print(f"\n  SOL {sol_id} [{l.product_id.default_code}] qty_del={l.qty_delivered}")
    if not moves:
        print(f"    [!] KHÔNG CÓ stock.move nào liên kết!")
    else:
        for mv in moves:
            print(f"    move id={mv.id}  state={mv.state:12}  "
                  f"qty={mv.product_uom_qty:.1f}  done={mv.quantity:.1f}"
                  f"  bom_line_id={mv.bom_line_id.id if mv.bom_line_id else 'NULL'}"
                  f"  [{mv.product_id.default_code or ''}]")

# ─── E. combo.product records ─────────────────────────────────────────────────
sec("E. combo.product RECORDS")

tmpl_ids_with_bom = [bom.product_tmpl_id.id for bom in kits]
combo_recs = env['combo.product'].sudo().search([
    ('product_template_id', 'in', tmpl_ids_with_bom)
]) if tmpl_ids_with_bom else []
if not combo_recs:
    print("  [!] Không có combo.product records cho các BOM kits này")
else:
    for cp in combo_recs:
        print(f"  combo.product id={cp.id}"
              f"  parent_tmpl={cp.product_template_id.id} [{cp.product_template_id.default_code or ''}]"
              f"  component={cp.product_id.id} [{cp.product_id.default_code or ''}]"
              f"  qty={cp.product_quantity}")

# ─── F. is_combo flag trên product.template ───────────────────────────────────
sec("F. is_combo FLAG TRÊN PRODUCT.TEMPLATE")

for bom in kits:
    tmpl = bom.product_tmpl_id
    is_combo = getattr(tmpl, 'is_combo', 'field_not_found')
    print(f"  tmpl id={tmpl.id}  [{tmpl.default_code or ''}]  is_combo={is_combo}")

# ─── G. Tóm tắt chẩn đoán ────────────────────────────────────────────────────
sec("G. TÓM TẮT CHẨN ĐOÁN")
print(f"  Số phantom BOM: {len(kits)}")
for bom in kits:
    bom_qty = bom.product_qty or 1.0
    ratio = float('inf')
    any_comp_in_sol = False
    for bl in bom.bom_line_ids:
        if not bl.product_id:
            continue
        qty_per_kit = (bl.product_qty or 0.0) / bom_qty
        if qty_per_kit > 0:
            delivered = sol_by_prod.get(bl.product_id.id, 0.0)
            if delivered > 0:
                any_comp_in_sol = True
            ratio = min(ratio, delivered / qty_per_kit)
    eff = min(ratio, 1.0) if ratio != float('inf') else 0.0
    print(f"\n  [{bom.product_tmpl_id.default_code or bom.product_tmpl_id.name}]")
    print(f"    kit_fallback_ratio={ratio:.3f}  eff_qty_del={eff:.3f}"
          f"  any_comp_in_sol={any_comp_in_sol}")
    if ratio == float('inf'):
        print(f"    → BOM KHÔNG CÓ LINH KIỆN nào → fallback không hoạt động")
    elif ratio == 0:
        print(f"    → LINH KIỆN CHƯA ĐƯỢC GIAO dưới dạng standalone SOL")
    else:
        print(f"    → OK: fallback nên hoạt động")

print(f"\n{SEP}")
print("  Done.")
print(SEP)
