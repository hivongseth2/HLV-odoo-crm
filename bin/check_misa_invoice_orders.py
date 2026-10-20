# -*- coding: utf-8 -*-
"""
check_misa_invoice_orders.py
============================
Vì sao các ĐƠN chỉ định còn lệch đối soát MISA — in đủ để đọc tay, không cần đơn nằm trong
khung "Vì sao còn lệch" (check_misa_invoice_gap_reasons.py lọc theo tháng / sale / top lệch).

Với mỗi đơn trong ORDER_NAMES:
  A. Odoo  : dòng đơn bán (đặt / giao / giá / thuế), số theo đơn đang lưu (tiền HĐ, nguồn), từng
             phiếu xuất: thực xuất, HĐ đã chia, lệch, trạng thái, đề nghị, ăn theo, dòng gộp đã khớp.
  B. Lý do : misa.invoice.gap.review.review_orders — cùng service báo cáo AI hằng ngày dùng:
             mã lý do, đề nghị tính cho đơn, so từng mã hàng (thiếu / thừa / thuế / giá), hải quan.
  C. MISA  : mọi đề nghị tìm theo mã đơn + theo tên từng phiếu, MỌI dòng hàng (kể cả đơn khác /
             trống mã đơn) — để thấy dòng ghi nhầm mã đơn, đề nghị gộp, đề nghị trùng.

CHỈ ĐỌC — không write/create/unlink gì. Có gọi API MISA (đọc).

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    cd ~/src/user
    odoo-bin shell -d <TEN_DATABASE> < bin/check_misa_invoice_orders.py
"""

ORDER_NAMES = ['DH125524949235907', 'DH125524949237496']
SEP = "=" * 100

REASON_LABELS = {
    'no_invoice': 'CHƯA CÓ ĐỀ NGHỊ / HĐ → sale lập đề nghị',
    'pending_request': 'ĐỀ NGHỊ CHƯA PHÁT HÀNH → kế toán phát hành',
    'missing_items': 'HĐ THIẾU MÃ đã giao → sale lập đề nghị bổ sung',
    'extra_items': 'HĐ THỪA MÃ / SL so với đã giao → kế toán kiểm HĐ',
    'tax_diff': 'KHÁC % THUẾ giữa đơn bán và HĐ',
    'price_diff': 'KHÁC ĐƠN GIÁ giữa đơn bán và HĐ',
    'duplicate_request': 'ĐỀ NGHỊ TRÙNG → xóa bớt, KHÔNG phát hành thêm',
    'customs_unmatched': 'HĐ HẢI QUAN CHƯA KHỚP PHIẾU → khớp tay ở tab Đơn hải quan',
    'mislabeled': 'DÒNG GHI NHẦM / BỎ TRỐNG MÃ ĐƠN → soát lại theo đơn sẽ tự chuyển',
    'stale': 'SỐ THEO ĐƠN ĐANG LƯU CŨ → soát lại theo đơn',
    'not_checked': 'ĐƠN CHƯA SOÁT THEO ĐƠN → soát lại theo đơn',
}
DETAIL_KEYS = ('missing', 'extra', 'tax_diff', 'price_diff')

Review = env['misa.invoice.gap.review'].sudo()
Picking = env['stock.picking'].sudo()
misa = env['misa.api.utils']


def money(v):
    return f"{(v or 0.0):,.0f}".replace(",", ".")


def print_odoo(order):
    print(f"\n  A. ODOO — {order.partner_id.commercial_partner_id.name}")
    for line in order.order_line.filtered(lambda l: not l.display_type):
        print(f"    [{line.product_id.default_code}] đặt {line.product_uom_qty:g} giao {line.qty_delivered:g}"
              f" | giá {money(line.price_unit)} | {money(line.price_subtotal)} trước thuế"
              f" | {', '.join(line.tax_id.mapped('name')) or 'không thuế'}")
    print(f"    Theo đơn: HĐ {money(order.misa_invoice_order_invoiced_amount)}"
          f" | soát lúc {order.misa_invoice_order_checked_at or 'CHƯA SOÁT'}")
    for src in (order.misa_invoice_order_sources or '').splitlines():
        print(f"      nguồn: {src}")
    total_gap = 0.0
    for p in order._misa_invoice_done_out_pickings():
        gap = Review._picking_gap(p)
        total_gap += gap
        items = ', '.join(f"{m.product_id.default_code}×{m.quantity:g}"
                          for m in p.move_ids_without_package if m.state == 'done')
        print(f"    ▸ {p.name} ({p.date_done:%d/%m/%Y}) {items}")
        print(f"        thực xuất {money(p.misa_invoice_net_actual_amount)} | HĐ chia {money(p.misa_invoice_allocated_amount)}"
              f" | lệch {money(gap)} | {p.misa_invoice_state} | đề nghị {p.misa_invoice_request_refno or '—'}"
              f" | HĐ {p.misa_invoice_no or '—'} | gắn tay {p.misa_invoice_manual_refno or '—'}"
              f" | ăn theo {p.misa_invoice_master_picking_id.name or '—'}")
        for match in p.misa_invoice_grouped_match_ids:
            print(f"        khớp dòng gộp của {match.line_id.master_picking_id.name}: "
                  f"[{match.line_id.inventory_item_code}] {match.quantity:g}/{match.line_id.quantity:g} {money(match.amount)}")
    print(f"    LỆCH CẢ ĐƠN: {money(total_gap)}")


def print_review(review):
    print("\n  B. LÝ DO (misa.invoice.gap.review)")
    if review.get('error'):
        print(f"    ❌ lỗi gọi MISA: {review['error']}")
        return
    print(f"    HĐ đã phát hành tính cho đơn: {money(review['issued_now'])} | đang lưu {money(review['stored_invoiced'])}")
    for req in review['requests']:
        state = f"HĐ {req['inv_no']}" if req['inv_no'] else 'chưa phát hành'
        print(f"    đề nghị {req['refno']} {state}: {money(req['amount'])}"
              + (f" — {'; '.join(req['notes'])}" if req['notes'] else ''))
    for line in review['customs']:
        print(f"    HĐ hải quan {line['invoice_no']} [{line['item']}] SL {line['qty']:g} {money(line['amount'])}"
              f" ({line['state']}, còn {line['remaining']:g})")
    for key in DETAIL_KEYS:
        for text in review.get(key) or []:
            print(f"    {key}: {text}")
    for dup in review['duplicates']:
        print(f"    trùng {money(dup['amount'])}: {', '.join(refno for refno, _inv in dup['requests'])}")
    for reason in review['reasons'] or ['unexplained']:
        print(f"    ⇒ {REASON_LABELS.get(reason, 'Mặt hàng khớp — lệch do chia tiền giữa các phiếu / đơn gộp')}")


def print_misa(order):
    print("\n  C. MISA — mọi đề nghị của đơn, mọi dòng hàng")
    requests = {r['refid']: r for r in misa.get_invoice_requests_for_order(order.name)}
    for p in order._misa_invoice_done_out_pickings():
        status = misa.get_invoice_status_for_refno(p.name)
        print(f"    tra tên {p.name}: {status['state']} | đề nghị {status.get('master_refno') or '—'}"
              f" | HĐ {status.get('invoice_no') or '—'} {money(status.get('invoice_amount'))}")
        if status.get('request_refid') and status['request_refid'] not in requests:
            requests[status['request_refid']] = {'refno': status.get('master_refno') or '',
                                                 'refid': status['request_refid'],
                                                 'inv_no': status.get('invoice_no') or ''}
    if not requests:
        print("    (MISA không có đề nghị nào nhắc mã đơn / tên phiếu của đơn)")
    for req in requests.values():
        print(f"    ▸ đề nghị {req['refno']} | HĐ {req['inv_no'] or 'CHƯA PHÁT HÀNH'}")
        for line in misa.get_invoice_request_lines(req['refid']):
            code = (line.get('order_code') or '').strip()
            mark = '' if code == order.name else '  ← đơn khác' if code else '  ← TRỐNG mã đơn'
            amount = (line.get('amount_oc') or 0.0) + (line.get('vat_amount_oc') or 0.0)
            print(f"        {code or '—'} [{line.get('inventory_item_code') or ''}] SL {line.get('quantity') or 0:g}"
                  f" × {money(line.get('unit_price'))} = {money(amount)} có VAT{mark}")


orders = env['sale.order'].sudo().with_context(active_test=False).search([('name', 'in', ORDER_NAMES)])
reviews = {r['id']: r for r in Review.review_orders(orders.ids)}
for order in orders:
    print(f"\n{SEP}\n  {order.name}\n{SEP}")
    print_odoo(order)
    print_review(reviews.get(order.id, {'error': 'không soát được'}))
    print_misa(order)
missing = set(ORDER_NAMES) - set(orders.mapped('name'))
if missing:
    print(f"\n  ❌ Không thấy đơn: {', '.join(sorted(missing))}")
print(SEP)
