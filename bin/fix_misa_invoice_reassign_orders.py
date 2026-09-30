# -*- coding: utf-8 -*-
"""
fix_misa_invoice_reassign_orders.py
===================================
Soát lại theo đơn với MISA (sale.order._misa_invoice_refresh_order_truth) cho các đơn có dòng đề
nghị ghi nhầm / bỏ trống mã đơn — thay cho bấm "Kiểm tra MISA ngay" từng đơn. Danh sách ORDERS
lấy từ bin/check_misa_invoice_line_reassign.py (cả đơn ghi trên dòng lẫn đơn nhận dòng).

DRY_RUN = True (mặc định): tính thử tiền HĐ theo đơn mới (có chuyển dòng) và in so với số đang
lưu — gọi MISA để đọc, KHÔNG ghi gì. Đặt False để soát thật: ghi số theo đơn mới, chia lại tiền
HĐ về phiếu, tự commit.

Cần server đã chạy bản có models/misa_invoice_line_reassign.py nối vào soát theo đơn.

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/fix_misa_invoice_reassign_orders.py
"""

DRY_RUN = True
ORDERS = [
    'DH125524949232207', 'DH125524949235474',   # KBC/OUT/09323 → KBC/OUT/12296
    'DH125524949234991', 'DH125524949234488',   # UT6581 1/2 → KBC/OUT/11375
    'DH125524949234640', 'DH125524949234889',   # EA20060B 5/13 → KBC/OUT/11906
    'DH125524949236148', 'DH125524949236036',   # NLMDC4L 1/5 → KBC/OUT/12930
    'DH125524949235919', 'DH125524949235944',   # AW-68-18L 2/4 → KBC/OUT/12645
    'DH125524949231948', 'DH125524949232095',   # BANHNIDEN 40/50 → KBC/OUT/09193
    'DH125524949233273', 'DH125524949233938',   # DCB127 2/4 → KBC/OUT/10940
]
SEP = "=" * 100

SaleOrder = env['sale.order'].sudo()
if not hasattr(SaleOrder, '_misa_invoice_owned_request_amounts'):
    raise SystemExit("❌ Server chưa có bản nối chuyển dòng vào soát theo đơn — deploy trước.")


def money(v):
    return f"{(v or 0.0):,.0f}".replace(",", ".")


def order_gap(order):
    return sum(
        (p.misa_invoice_net_actual_amount or 0.0) - (p.misa_invoice_allocated_amount or 0.0)
        for p in order._misa_invoice_done_out_pickings()
    )


orders = SaleOrder.search([('name', 'in', ORDERS)])
missing = set(ORDERS) - set(orders.mapped('name'))
print(f"\n{SEP}\n  SOÁT LẠI THEO ĐƠN (có chuyển dòng ghi nhầm mã đơn) — {'CHẠY THỬ' if DRY_RUN else 'GHI THẬT'}:"
      f" {len(orders)} đơn" + (f" — không tìm thấy {', '.join(sorted(missing))}" if missing else '') + f"\n{SEP}")

if DRY_RUN:
    requests_cache, lines_cache = {}, {}
    for order in orders:
        try:
            moves, lines = order._misa_invoice_line_moves(requests_cache, lines_cache)
            owned = order._misa_invoice_owned_request_amounts(moves, lines)
        except Exception as e:
            print(f"\n  ❌ {order.name}: lỗi gọi MISA — {e}")
            continue
        issued = sum(amount for req, amount, _notes in owned if req['inv_no'])
        print(f"\n  {order.name} | đang lệch {money(order_gap(order))} | HĐ theo đơn đang lưu"
              f" {money(order.misa_invoice_order_invoiced_amount)} → sẽ là {money(issued)}")
        for req, amount, notes in owned:
            if notes:
                print(f"      {req['refno']} HĐ {req['inv_no'] or '(chưa phát hành)'}: {money(amount)} — {'; '.join(notes)}")
else:
    before = {order.id: order_gap(order) for order in orders}
    orders._misa_invoice_refresh_order_truth()
    env.cr.commit()
    orders.invalidate_recordset()
    for order in orders:
        print(f"\n  {order.name} | lệch {money(before[order.id])} → {money(order_gap(order))}"
              f" | HĐ theo đơn {money(order.misa_invoice_order_invoiced_amount)}")
        for source in (order.misa_invoice_order_sources or '').splitlines():
            if 'chuyển' in source or 'nhận' in source:
                print(f"      {source}")

print(f"\n{SEP}")
print("  CHẠY THỬ — chưa ghi gì. Đặt DRY_RUN = False rồi chạy lại." if DRY_RUN else "  ĐÃ GHI + COMMIT.")
print(SEP)
