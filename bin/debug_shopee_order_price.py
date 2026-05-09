#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Debug giá đơn hàng Shopee trong Odoo.

Chạy:
    odoo-bin shell -c <odoo.conf> --no-http < bin/debug_shopee_order_price.py

Mục đích: Trace toàn bộ logic update_order_lines_from_escrow + apply_escrow_voucher
để tìm nguyên nhân giá tính sai.
"""

ORDER_NAME = "S03030"

# ─────────────────────────────────────────────────────────────────────────────
SEP  = "=" * 70
SEP2 = "-" * 70

def f(val):
    """Format số tiền VND"""
    if isinstance(val, (int, float)):
        return "{:,.2f}đ".format(val)
    return str(val)

def pct(val):
    return "{:.5f}%".format(val)

# ─────────────────── 1. Đọc đơn hàng ────────────────────────────────────────
so = env['sale.order'].sudo().search([('name', '=', ORDER_NAME)], limit=1)
if not so:
    print(f"[LỖI] Không tìm thấy đơn hàng: {ORDER_NAME}")
    raise SystemExit(1)

print(SEP)
print(f"ĐƠN HÀNG: {so.name}  |  Shopee ref: {so.shopee_order_ref}  |  State: {so.state}")
print(SEP)

escrow_data = so.shopee_escrow_data
if not escrow_data:
    print("[LỖI] Đơn hàng chưa có shopee_escrow_data. Bấm nút 'Cập nhật giá Shopee' trước.")
    raise SystemExit(1)

# ─────────────────── 2. Trạng thái hiện tại của order lines ─────────────────
print("\n[HIỆN TẠI] Các dòng hàng trong Odoo:")
print(f"  {'SKU':<25} {'price_unit':>14} {'qty':>5} {'discount':>12} {'subtotal':>14} {'tax':>20}")
print(SEP2)
for line in so.order_line.filtered(lambda l: not l.display_type):
    tax_names = ", ".join(line.tax_id.mapped('name')) or "(không có)"
    tax_include = ", ".join(
        "incl" if t.price_include else "excl" for t in line.tax_id
    ) or "-"
    subtotal = line.price_unit * line.product_uom_qty * (1 - line.discount / 100)
    print(f"  {line.product_id.default_code or line.product_id.name:<25}"
          f" {f(line.price_unit):>14} {line.product_uom_qty:>5.0f}"
          f" {pct(line.discount):>12} {f(subtotal):>14}"
          f"  {tax_names} ({tax_include})")

total_untaxed = so.amount_untaxed
total_tax     = so.amount_tax
total_total   = so.amount_total
print(SEP2)
print(f"  {'Trước thuế':>57} {f(total_untaxed):>14}")
print(f"  {'Thuế':>57} {f(total_tax):>14}")
print(f"  {'TỔNG':>57} {f(total_total):>14}")

# ─────────────────── 3. Đọc dữ liệu escrow ──────────────────────────────────
print(f"\n{SEP}")
print("[ESCROW DATA] order_income:")
order_income = escrow_data.get('order_income', {})

voucher_from_seller_oi = order_income.get('voucher_from_seller', 0)
buyer_payment          = escrow_data.get('buyer_payment_info', {})
seller_voucher_bp      = buyer_payment.get('seller_voucher', 0)

# Key fields từ order_income
for key in ['buyer_total_amount', 'original_cost', 'seller_discount',
            'voucher_from_seller', 'shopee_discount', 'coins',
            'escrow_amount', 'final_product_payout']:
    val = order_income.get(key)
    if val is not None:
        print(f"  order_income.{key:<30} = {f(val)}")

print(f"\n  buyer_payment_info.seller_voucher        = {f(seller_voucher_bp)}")

# Quyết định voucher nào được dùng
if voucher_from_seller_oi:
    used_voucher = abs(voucher_from_seller_oi)
    voucher_source = "order_income.voucher_from_seller"
else:
    used_voucher = abs(seller_voucher_bp)
    voucher_source = "buyer_payment_info.seller_voucher (fallback)"

print(f"\n  → Voucher dùng để phân bổ: {f(used_voucher)}  (từ {voucher_source})")

# ─────────────────── 4. Simulate update_order_lines_from_escrow ─────────────
print(f"\n{SEP}")
print("[SIMULATE] update_order_lines_from_escrow:")
print(f"  {'SKU':<25} {'qty':>5} {'original_price':>16} {'discounted_price':>18} {'discount':>12} {'x_thanh_tien':>14}")
print(SEP2)

item_list = order_income.get('items', [])
if not item_list:
    print("  [!] order_income.items rỗng → update_order_lines_from_escrow KHÔNG chạy gì cả!")
else:
    for item_data in item_list:
        sku = item_data.get('model_sku', '') or item_data.get('item_sku', '')
        qty = item_data.get('quantity_purchased', 1) or 1
        orig_total    = item_data.get('original_price', 0)
        disc_total    = item_data.get('discounted_price', 0)
        orig_per_unit = orig_total / qty
        disc_per_unit = disc_total / qty

        discount = 0.0
        if orig_per_unit > 0:
            discount = (orig_per_unit - disc_per_unit) / orig_per_unit * 100.0

        line = so.order_line.filtered(lambda l: l.product_id.default_code == sku)
        matched = f"✓ khớp" if line else "✗ KHÔNG KHỚP line nào"
        print(f"  {(sku or '(no sku)'):<25} {qty:>5.0f}"
              f" {f(orig_per_unit):>16} {f(disc_per_unit):>18}"
              f" {pct(discount):>12} {f(disc_total):>14}  [{matched}]")

# ─────────────────── 5. Simulate apply_escrow_voucher ───────────────────────
print(f"\n{SEP}")
print("[SIMULATE] apply_escrow_voucher:")

if used_voucher <= 0:
    print(f"  [!] total_voucher = 0 → hàm return ngay, KHÔNG phân bổ voucher nào!")
    print(f"      *** ĐÂY CÓ THỂ LÀ NGUYÊN NHÂN GIÁ SAI ***")
else:
    print(f"  total_voucher = {f(used_voucher)}")
    lines = so.order_line.filtered(lambda l: not l.display_type and l.price_unit > 0)
    total_before = sum(
        l.price_unit * l.product_uom_qty * (1 - l.discount / 100.0)
        for l in lines
    )
    print(f"  total_before_voucher (subtotal hiện tại) = {f(total_before)}")

    if total_before <= 0:
        print("  [!] total_before_voucher <= 0 → return luôn, không phân bổ!")
    else:
        for i, line in enumerate(list(lines)):
            line_total = line.price_unit * line.product_uom_qty
            line_sub   = line_total * (1 - line.discount / 100.0)
            share      = (line_sub / total_before) * used_voucher
            new_sub    = line_sub - share
            new_disc   = (1 - new_sub / line_total) * 100.0 if line_total > 0 else 0
            sku        = line.product_id.default_code or line.product_id.name
            print(f"  SKU={sku}: subtotal {f(line_sub)} - voucher {f(share)} = {f(new_sub)}, discount mới = {pct(new_disc)}")

# ─────────────────── 6. Tính expected vs actual ──────────────────────────────
print(f"\n{SEP}")
print("[PHÂN TÍCH GIÁ]")

# Tính expected từ escrow
expected_before_voucher = 0.0
for item_data in item_list:
    qty = item_data.get('quantity_purchased', 1) or 1
    disc_total = item_data.get('discounted_price', 0)
    expected_before_voucher += disc_total

expected_after_voucher = expected_before_voucher - used_voucher

print(f"  Tổng discounted_price (escrow items)            = {f(expected_before_voucher)}")
print(f"  Trừ voucher_from_seller                         = {f(used_voucher)}")
print(f"  → Expected subtotal (trước thuế, incl-tax view) = {f(expected_after_voucher)}")
print()
print(f"  Actual Odoo amount_total                        = {f(total_total)}")
print(f"  Actual Odoo amount_untaxed                      = {f(total_untaxed)}")
print()

diff = total_total - expected_after_voucher
print(f"  Chênh lệch (actual - expected)                  = {f(diff)}")

# Kiểm tra tax type
print(f"\n{SEP}")
print("[KIỂM TRA THUẾ trên order lines]")
for line in so.order_line.filtered(lambda l: not l.display_type and l.tax_id):
    for tax in line.tax_id:
        inc = "✓ price_include=True (GIÁ BAO GỒM THUẾ - đúng cho Shopee)" \
              if tax.price_include else \
              "✗ price_include=False (CỘNG THÊM THUẾ VÀO GIÁ - sai! sẽ bị tính thừa thuế)"
        print(f"  SKU={line.product_id.default_code}: {tax.name} → {inc}")

print(f"\n{SEP}")
print("XONG. Xem phân tích ở trên để tìm nguyên nhân.")
print(SEP)
