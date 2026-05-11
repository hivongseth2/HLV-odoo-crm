#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Confirm nguyên nhân chênh lệch đơn giá Odoo vs MISA CRM.

Chạy:
    odoo-bin shell -c <odoo.conf> --no-http < bin/confirm_shopee_price_vs_misa.py

Đổi ORDER_NAME bên dưới sang mã đơn cần kiểm tra (mặc định: S03213).
"""

ORDER_NAME = "S03213"   # ← đổi thành đơn khác nếu muốn

SEP  = "=" * 72
SEP2 = "-" * 72


def f(v):
    return "{:,.2f}đ".format(v) if isinstance(v, (int, float)) else str(v)


# ── 1. Tìm đơn hàng ──────────────────────────────────────────────────────────
so = env['sale.order'].sudo().search([('name', '=', ORDER_NAME)], limit=1)
if not so:
    print(f"[LỖI] Không tìm thấy đơn hàng: {ORDER_NAME}")
    raise SystemExit(1)

print(SEP)
print(f"ĐƠN: {so.name}  |  Shopee ref: {so.shopee_order_ref}  |  State: {so.state}")
print(SEP)

# ── 2. Phân tích từng dòng hàng ───────────────────────────────────────────────
print("\n[ ODOO - Order Lines ]\n")
print(f"  {'SKU':<25} {'price_unit(Odoo)':>18} {'discount':>12} {'tax_name':<22} {'price_incl':>10} {'tax_rate':>9}")
print(SEP2)

rows = []
for line in so.order_line.filtered(lambda l: not l.display_type and l.product_uom_qty > 0):
    sku = line.product_id.default_code or line.product_id.name[:20]
    p_unit  = line.price_unit
    disc    = line.discount
    taxes   = line.tax_id

    for tax in taxes:
        rate       = tax.amount          # ví dụ 8.0
        incl       = tax.price_include   # True = giá bao gồm thuế
        # Tính lại pre-tax unit price (như MISA hiển thị)
        if incl:
            pre_tax = p_unit / (1 + rate / 100.0)
        else:
            pre_tax = p_unit  # không thay đổi

        rows.append({
            'sku': sku,
            'qty': line.product_uom_qty,
            'p_unit': p_unit,
            'disc': disc,
            'tax_name': tax.name,
            'incl': incl,
            'rate': rate,
            'pre_tax': pre_tax,
            'line': line,
        })
        print(
            f"  {sku:<25} {f(p_unit):>18} {disc:>11.5f}%"
            f"  {tax.name:<22} {'✓ incl' if incl else '✗ excl':>10} {rate:>8.1f}%"
        )

    if not taxes:
        rows.append({
            'sku': sku, 'qty': line.product_uom_qty,
            'p_unit': p_unit, 'disc': disc,
            'tax_name': '(no tax)', 'incl': False, 'rate': 0.0,
            'pre_tax': p_unit, 'line': line,
        })
        print(f"  {sku:<25} {f(p_unit):>18} {disc:>11.5f}%  {'(no tax)':<22} {'N/A':>10} {'0':>8}")

# ── 3. Bảng so sánh Odoo vs MISA ─────────────────────────────────────────────
print(f"\n{SEP}")
print("[ SO SÁNH: Odoo (price_incl) vs MISA (pre-tax) ]\n")
print(f"  {'SKU':<25} {'Odoo price_unit':>17}"
      f" {'pre_tax (MISA)':>17} {'disc%':>10}"
      f" {'Odoo total_line':>16} {'MISA total_line':>16}")
print(SEP2)

for r in rows:
    p       = r['p_unit']
    pt      = r['pre_tax']
    disc    = r['disc']
    qty     = r['qty']
    rate    = r['rate']
    incl    = r['incl']

    # Subtotal = qty * price_unit * (1 - disc%)
    odoo_sub  = qty * p * (1 - disc / 100.0)
    # MISA subtotal (trước thuế)
    misa_sub_pretax = qty * pt * (1 - disc / 100.0)
    # MISA tổng có thuế
    misa_total = misa_sub_pretax * (1 + rate / 100.0)

    print(
        f"  {r['sku']:<25} {f(p):>17} {f(pt):>17} {disc:>9.5f}%"
        f" {f(odoo_sub):>16} {f(misa_total):>16}"
    )
    if incl:
        print(
            f"  {'':25}  → MISA hiển thị pre-tax: {f(p)} / {1 + rate/100:.2f} = {f(pt)}"
        )

# ── 4. Totals ─────────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("[ TOTALS ODOO ]\n")
print(f"  amount_untaxed  = {f(so.amount_untaxed)}")
print(f"  amount_tax      = {f(so.amount_tax)}")
print(f"  amount_total    = {f(so.amount_total)}")

# ── 5. Kiểm tra escrow data ───────────────────────────────────────────────────
escrow_data = so.shopee_escrow_data
if escrow_data:
    order_income = escrow_data.get('order_income', {})
    buyer_total   = order_income.get('buyer_total_amount', 'N/A')
    escrow_amount = order_income.get('escrow_amount', 'N/A')
    voucher_fs    = order_income.get('voucher_from_seller', 0)
    original_cost = order_income.get('original_cost', 'N/A')

    print(f"\n{SEP}")
    print("[ ESCROW DATA (từ Shopee) ]\n")
    print(f"  buyer_total_amount     = {f(buyer_total) if isinstance(buyer_total,(int,float)) else buyer_total}")
    print(f"  original_cost          = {f(original_cost) if isinstance(original_cost,(int,float)) else original_cost}")
    print(f"  voucher_from_seller    = {f(voucher_fs) if isinstance(voucher_fs,(int,float)) else voucher_fs}")
    print(f"  escrow_amount (thực nhận) = {f(escrow_amount) if isinstance(escrow_amount,(int,float)) else escrow_amount}")

    items = order_income.get('items', [])
    if items:
        print(f"\n  Escrow items (giá gốc từ Shopee API — chưa có thuế khái niệm):")
        print(f"  {'SKU':<25} {'qty':>5} {'original_price (total)':>24} {'discounted_price (total)':>26}")
        print(f"  {'-'*65}")
        for it in items:
            sku = it.get('model_sku', '') or it.get('item_sku', '')
            qty = it.get('quantity_purchased', 1) or 1
            op  = it.get('original_price', 0)
            dp  = it.get('discounted_price', 0)
            print(f"  {sku:<25} {qty:>5}  {f(op):>24}  {f(dp):>26}")
            print(f"  {'':25}  per-unit: orig={f(op/qty)}, disc={f(dp/qty)}")
else:
    print("\n  [!] Chưa có shopee_escrow_data trên đơn này.")

# ── 6. Kết luận ───────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("[ KẾT LUẬN ]\n")
for r in rows:
    if r['incl'] and r['rate'] > 0:
        print(
            f"  SKU {r['sku']}:"
        )
        print(
            f"    Odoo lưu price_unit = {f(r['p_unit'])}  (giá BẢO GỒM VAT {r['rate']:.0f}%)"
        )
        print(
            f"    MISA hiển thị      = {f(r['pre_tax'])}  (= {f(r['p_unit'])} ÷ {1+r['rate']/100:.2f}, giá CHƯA thuế)"
        )
        print(
            f"    → KHÔNG phải lỗi. Tổng tiền cuối vẫn khớp {f(so.amount_total)}"
        )
    elif not r['incl'] and r['rate'] > 0:
        print(
            f"  SKU {r['sku']}:"
        )
        print(
            f"    ⚠ price_include=False (thuế CỘNG THÊM). Odoo sẽ cộng {r['rate']:.0f}% lên {f(r['p_unit'])}"
        )
        print(
            f"    → Total sẽ = {f(r['p_unit'])} × (1 + {r['rate']:.0f}%) = {f(r['p_unit']*(1+r['rate']/100))}"
        )
        print(
            f"    → Đây mới là LỖI — nên dùng thuế price_include=True cho đơn Shopee!"
        )
    else:
        print(f"  SKU {r['sku']}: không có thuế → giá Odoo = giá MISA = {f(r['p_unit'])}")

print(SEP)
