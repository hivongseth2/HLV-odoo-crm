# -*- coding: utf-8 -*-
"""
shopee_orders_april2026.py
==========================
Lấy tất cả đơn Shopee tháng 4/2026 có trạng thái:
  - SHIPPED / Đang giao
  - RETRY_SHIP / Giao lại
  - PROCESSED / Đã xử lý
  - READY_TO_SHIP / Chờ lấy hàng
  - UNPAID / Chưa thanh toán
  (tìm cả mã tiếng Anh lẫn nhãn tiếng Việt)
  => Cập nhật tất cả thành "Đã nhận hàng"

Chạy:
    python odoo-bin shell -d <DATABASE> < bin/shopee_orders_april2026.py

Output: danh sách đơn kèm thông tin cơ bản, xuất ra console và file CSV.
"""

import csv
import os
from datetime import datetime

DATE_FROM = '2026-04-01 00:00:00'
DATE_TO   = '2026-04-30 23:59:59'
STATUSES  = [
    # Tiếng Anh (Shopee code)
    'SHIPPED', 'RETRY_SHIP', 'PROCESSED', 'READY_TO_SHIP', 'UNPAID',
    # Tiếng Việt (có thể được lưu thay vì code)
    'Đang giao', 'Giao lại', 'Đã xử lý', 'Chờ lấy hàng', 'Chưa thanh toán',
]

# Map chuẩn hóa: cả EN lẫn VI đều về nhãn hiển thị
STATUS_LABEL = {
    'SHIPPED':       'Đang giao',
    'RETRY_SHIP':    'Giao lại',
    'PROCESSED':     'Đã xử lý',
    'READY_TO_SHIP': 'Chờ lấy hàng',
    'UNPAID':        'Chưa thanh toán',
    'Đang giao':     'Đang giao',
    'Giao lại':      'Giao lại',
    'Đã xử lý':      'Đã xử lý',
    'Chờ lấy hàng': 'Chờ lấy hàng',
    'Chưa thanh toán': 'Chưa thanh toán',
}
OUT_FILE  = '/tmp/shopee_orders_april2026.csv'

SEP  = "=" * 80
SEP2 = "-" * 60

def sec(t): print(f"\n{SEP}\n  {t}\n{SEP}")
def sub(t): print(f"\n  {SEP2}\n  {t}\n  {SEP2}")

# ─── Tìm đơn hàng ────────────────────────────────────────────────────────────
sec(f"ĐƠN SHOPEE THÁNG 4/2026 — TRẠNG THÁI: {', '.join(STATUSES)}")

orders = env['sale.order'].sudo().search([
    ('shopee_order_status', 'in', STATUSES),
    ('date_order', '>=', DATE_FROM),
    ('date_order', '<=', DATE_TO),
], order='date_order asc')

print(f"  Tổng số đơn tìm được: {len(orders)}")

if not orders:
    print("  [!] Không tìm thấy đơn nào phù hợp.")
    raise SystemExit

# ─── Phân loại theo trạng thái ───────────────────────────────────────────────
by_status = {}
for o in orders:
    s = o.shopee_order_status or 'UNKNOWN'
    by_status.setdefault(s, []).append(o)

for s, lst in sorted(by_status.items()):
    label = STATUS_LABEL.get(s, s)
    print(f"    {s:20} ({label:20}): {len(lst):>4} đơn")

# ─── In chi tiết từng đơn ────────────────────────────────────────────────────
sec("CHI TIẾT TỪNG ĐƠN")

header = (
    f"  {'#':>4}  {'Tên đơn':20}  {'Shopee Ref':25}  {'Trạng thái':20}"
    f"  {'Ngày đặt':20}  {'Khách hàng':30}  {'Tổng tiền':>12}  {'state Odoo'}"
)
print(header)
print(f"  {'-'*4}  {'-'*20}  {'-'*25}  {'-'*20}  {'-'*20}  {'-'*30}  {'-'*12}  {'-'*12}")

rows = []
for i, o in enumerate(orders, 1):
    shopee_ref   = getattr(o, 'shopee_order_ref', '') or ''
    shopee_st    = o.shopee_order_status or ''
    date_str     = o.date_order.strftime('%Y-%m-%d %H:%M') if o.date_order else ''
    partner_name = (o.partner_id.name or '')[:30]
    amount       = o.amount_total
    odoo_state   = o.state

    label = STATUS_LABEL.get(shopee_st, shopee_st)

    print(
        f"  {i:>4}  {o.name:20}  {shopee_ref:25}  {label:20}"
        f"  {date_str:20}  {partner_name:30}  {amount:>12,.0f}  {odoo_state}"
    )
    rows.append({
        'stt':            i,
        'ten_don':        o.name,
        'shopee_ref':     shopee_ref,
        'shopee_status':  shopee_st,
        'trang_thai_vi':  label,
        'ngay_dat':       date_str,
        'khach_hang':     o.partner_id.name or '',
        'tong_tien':      amount,
        'odoo_state':     odoo_state,
        'so_dien_thoai':  o.partner_id.phone or '',
        'so_line':        len(o.order_line.filtered(lambda l: not l.display_type)),
    })

# ─── Thống kê ─────────────────────────────────────────────────────────────────
sec("THỐNG KÊ")

for s, lst in sorted(by_status.items()):
    label = STATUS_LABEL.get(s, s)
    total_amt = sum(o.amount_total for o in lst)
    print(f"  {s} ({label}): {len(lst)} đơn  —  Tổng doanh thu: {total_amt:,.0f} VNĐ")

grand_total = sum(o.amount_total for o in orders)
print(f"\n  TỔNG CỘNG: {len(orders)} đơn  —  {grand_total:,.0f} VNĐ")

# ─── Xuất CSV ─────────────────────────────────────────────────────────────────
sec(f"XUẤT FILE CSV → {OUT_FILE}")

try:
    fieldnames = ['stt', 'ten_don', 'shopee_ref', 'shopee_status', 'trang_thai_vi',
                  'ngay_dat', 'khach_hang', 'so_dien_thoai', 'tong_tien', 'odoo_state', 'so_line']
    with open(OUT_FILE, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Đã ghi {len(rows)} dòng vào {OUT_FILE}")
except Exception as e:
    print(f"  [!] Không thể ghi file: {e}")

# ─── Cập nhật trạng thái → Đã nhận hàng ──────────────────────────────────────────
sec("CẬP NHẬT TRẠNG THÁI → Đã nhận hàng")

NEW_STATUS = 'Đã nhận hàng'
updated = 0
skipped = 0
errors  = 0

for o in orders:
    if o.shopee_order_status == NEW_STATUS:
        skipped += 1
        continue
    try:
        old = o.shopee_order_status
        o.sudo().write({'shopee_order_status': NEW_STATUS})
        print(f"  ✓ {o.name:20}  {old or '':25} → {NEW_STATUS}")
        updated += 1
    except Exception as e:
        print(f"  ✗ {o.name:20}  LỖI: {e}")
        errors += 1

env.cr.commit()

print(f"\n  Kết quả: cập nhật={updated}  bỏ qua (đã là Đã nhận hàng)={skipped}  lỗi={errors}")

print(f"\n{SEP}")
print("  Done.")
print(SEP)
