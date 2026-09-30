# -*- coding: utf-8 -*-
"""
check_misa_customs_invoice_number.py
====================================
1 HÓA ĐƠN trên MISA có thể lập gộp cho NHIỀU chứng từ bán hàng (mỗi chứng từ 1 refid, dòng hàng
riêng) — trong khi tab Đơn hải quan bản cũ chỉ đọc 1 chứng từ theo số hóa đơn. Case
nghi vấn: HĐ 00005319 trên MISA có 27 dòng (GPUT06, GPY06...), còn bản ghi 00005319 trong Odoo
chỉ có 5 dòng SMC của đơn DH125524949236010; 3 phiếu KBC/OUT/11284/11670/11098 từng khớp vào
"00005319" giờ không còn dòng nào.

Script in ĐỦ 2 phía cho từng số hóa đơn trong INV_NOS:
  - MISA : MỌI chứng từ bán hàng MISA trả về khi tìm số đó (kể cả dòng chỉ CHỨA số đó), với
           refid, ký hiệu/mẫu số, chi nhánh, khách, tổng tiền, và dòng hàng (mã đơn nào, bao
           nhiêu dòng). Dòng nào có mã đơn trong WATCH_ORDERS được đánh dấu.
  - Odoo : các dòng tab Đơn hải quan đang lưu số đó (refid nào, đơn nào, ghi nhận lúc nào),
           và các phiếu đang ghi misa_invoice_no = số đó.

CHỈ ĐỌC — không write/create/unlink gì. Có gọi API MISA (đọc).

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_misa_customs_invoice_number.py
"""

from collections import Counter

INV_NOS = ['00005319']
WATCH_ORDERS = ['DH125524949234371', 'DH125524949234597', 'DH125524949234106', 'DH125524949236010']
# Tên field MISA có thể mang ký hiệu/mẫu số/chi nhánh — in hết field nào tên chứa các chữ này.
FIELD_HINTS = ('inv', 'series', 'template', 'branch', 'organization', 'refno', 'refid', 'date', 'total', 'object')

SEP = "=" * 100
SUB = "-" * 100

misa = env['misa.api.utils'].sudo()
CustomsLine = env['misa.invoice.customs.line'].sudo()
Picking = env['stock.picking'].sudo()


def money(v):
    return f"{(v or 0.0):,.0f}".replace(",", ".")


def norm(v):
    return (v or '').strip().lstrip('0') or ''


for inv_no in INV_NOS:
    print(f"\n{SEP}\n  SỐ HÓA ĐƠN {inv_no}\n{SEP}")

    print(f"\n{SUB}\n  A. MISA — mọi chứng từ bán hàng trả về khi tìm '{inv_no}'\n{SUB}")
    try:
        vouchers = misa.get_vouchers_by_inv_no(inv_no)
    except Exception as e:
        print(f"  ❌ Lỗi gọi MISA: {type(e).__name__}: {e}")
        vouchers = []
    exact = [v for v in vouchers if norm(v.get('inv_no')) == norm(inv_no)]
    print(f"  MISA trả {len(vouchers)} chứng từ, {len(exact)} chứng từ đúng số {inv_no}")
    for idx, voucher in enumerate(vouchers, 1):
        mark = 'ĐÚNG SỐ' if voucher in exact else 'chỉ chứa chuỗi'
        print(f"\n  [{idx}] ({mark}) inv_no={voucher.get('inv_no')!r} refid={voucher.get('refid')!r}")
        for key in sorted(voucher):
            if any(h in key.lower() for h in FIELD_HINTS) and key not in ('inv_no', 'refid'):
                print(f"        {key:36s} = {voucher.get(key)!r}")
        try:
            lines = misa.get_voucher_lines(voucher.get('refid')) if voucher.get('refid') else []
        except Exception as e:
            print(f"        ❌ Lỗi đọc dòng hàng: {e}")
            continue
        orders = Counter((line.get('order_code') or '').strip() or '(trống)' for line in lines)
        print(f"        → {len(lines)} dòng hàng, tổng chưa VAT {money(sum(l.get('amount_oc') or 0 for l in lines))} đ")
        for order_code, count in orders.most_common():
            flag = '   ⬅ ĐƠN ĐANG SOÁT' if order_code in WATCH_ORDERS else ''
            print(f"          đơn {order_code:<22} {count:>3} dòng{flag}")
        watched = [l for l in lines if (l.get('order_code') or '').strip() in WATCH_ORDERS]
        for line in watched:
            print(f"            · {line.get('order_code')} {line.get('inventory_item_code')!r} SL={line.get('quantity')}"
                  f" tiền={money(line.get('amount_oc'))} VAT={line.get('vat_amount_oc')!r}")

    print(f"\n{SUB}\n  B. ODOO — tab Đơn hải quan đang lưu số {inv_no}\n{SUB}")
    lines = CustomsLine.search([('invoice_no', '=', inv_no)])
    print(f"  {len(lines)} dòng, refid đang lưu: {sorted(set(lines.mapped('invoice_refid')))}")
    for line in lines:
        print(f"    {line.order_code:<20} {line.inventory_item_code!r:<22} SL={line.quantity} tiền={money(line.amount)}"
              f" {line.match_state} | ghi nhận {line.fetched_at} bởi {line.fetched_by_id.name or '-'}"
              f" | khớp: {', '.join(line.match_ids.mapped('picking_id.name')) or '-'}")

    print(f"\n{SUB}\n  C. ODOO — phiếu đang ghi misa_invoice_no = {inv_no}\n{SUB}")
    for picking in Picking.search([('misa_invoice_no', '=', inv_no)]):
        print(f"    {picking.name:<16} state={picking.misa_invoice_state} đơn={', '.join(picking.misa_invoice_sale_order_ids.mapped('name'))}"
              f" XK={money(picking.misa_invoice_net_actual_amount)} HĐ={money(picking.misa_invoice_amount)}"
              f" request_refid={picking.misa_invoice_request_refid or '-'}")
        for msg in picking.message_ids.filtered(lambda m: 'hải quan' in (m.body or ''))[:5]:
            print(f"        [{msg.date}] {msg.author_id.name or '-'}: {msg.body[:160]}")

print(f"\n{SEP}")
print("  Đọc kết quả: mục A có >= 2 chứng từ ĐÚNG SỐ = hóa đơn gộp nhiều chứng từ bán hàng. So refid\n"
      "  ở mục B với mục A: chứng từ nào Odoo chưa có dòng thì ghi nhận lại số hóa đơn này (bản 1.13).")
print(SEP)
