# -*- coding: utf-8 -*-
"""
check_misa_invoice_gap_reasons.py
=================================
Mọi đơn đang lệch trong khung "Vì sao còn lệch" (lọc được theo sale / tháng xuất kho) — mỗi đơn
in gọn LÝ DO và NÊN LÀM GÌ. Logic nằm trong module (misa.invoice.gap.review — cùng chỗ báo cáo AI
hằng ngày dùng), file này chỉ in ra. Muốn xem chi tiết đủ A–E của 1 phiếu thì dùng
bin/check_misa_invoice_gap_pickings.py.

Cuối cùng in danh sách đơn mà SOÁT LẠI THEO ĐƠN là tự hết lệch — dán vào ORDERS của
bin/fix_misa_invoice_reassign_orders.py rồi chạy.

CHỈ ĐỌC — không write/create/unlink gì. Có gọi API MISA (đọc).

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_misa_invoice_gap_reasons.py
"""

from collections import defaultdict

SALER_CODE = False          # False = mọi sale; hoặc 'TRANTHIMYDUYEN'
MONTH = '2026-09'           # False = mọi tháng; hoặc '2026-08' (tháng xuất kho của phiếu lệch)
ONLY_ORDERS = []            # để trống = tự lấy theo 2 lọc trên; hoặc ['DH125524949235869', ...]
MAX_ORDERS = 300            # đơn lệch nhiều nhất trước
SEP = "=" * 100

REASON_LABELS = {
    'no_invoice': 'CHƯA XUẤT HĐ',
    'pending_request': 'ĐỀ NGHỊ CHƯA PHÁT HÀNH',
    'missing_items': 'HĐ THIẾU MÃ',
    'extra_items': 'HĐ THỪA MÃ',
    'tax_diff': 'SAI % THUẾ trên đơn bán',
    'price_diff': 'KHÁC ĐƠN GIÁ',
    'duplicate_request': 'ĐỀ NGHỊ TRÙNG → xóa bớt, KHÔNG phát hành thêm',
    'customs_unmatched': 'HĐ HẢI QUAN CHƯA KHỚP PHIẾU → khớp tay ở tab Đơn hải quan',
    'mislabeled': 'DÒNG GHI NHẦM / BỎ TRỐNG MÃ ĐƠN → soát lại theo đơn sẽ tự chuyển',
    'stale': 'SỐ THEO ĐƠN ĐANG LƯU CŨ → soát lại theo đơn',
    'not_checked': 'ĐƠN CHƯA SOÁT THEO ĐƠN → soát lại theo đơn',
}
DETAIL_KEYS = {'missing_items': 'missing', 'extra_items': 'extra', 'tax_diff': 'tax_diff', 'price_diff': 'price_diff'}

Review = env['misa.invoice.gap.review'].sudo()
if not hasattr(Review, 'review_orders'):
    raise SystemExit("❌ Server chưa có models/misa_invoice_gap_review.py — deploy trước.")


def money(v):
    return f"{(v or 0.0):,.0f}".replace(",", ".")


scope = Review.gap_orders(month=MONTH, saler_code=SALER_CODE, limit=MAX_ORDERS)
rows = scope['orders']
if ONLY_ORDERS:
    rows = [r for r in rows if r['name'] in ONLY_ORDERS]
print(f"\n{SEP}\n  VÌ SAO CÒN LỆCH — {len(rows)}/{scope['order_count']} đơn, tổng lệch {money(scope['total_gap'])}"
      f"{' | sale ' + SALER_CODE if SALER_CODE else ''}{' | tháng ' + MONTH if MONTH else ''}\n{SEP}")

reviews = {}
for start in range(0, len(rows), 20):
    for review in Review.review_orders([r['id'] for r in rows[start:start + 20]]):
        reviews[review['id']] = review

refresh_fixes = []
reason_count = defaultdict(int)
for row in rows:
    review = reviews.get(row['id'], {})
    print(f"\n  {row['name']} — {row['partner']} | lệch cả đơn {money(row['gap'])} | {row['age_days']} ngày"
          f" | phiếu lệch: {', '.join('%s (%s)' % (p['name'], money(p['gap'])) for p in row['gap_pickings'])}")
    if review.get('error'):
        print(f"      ❌ lỗi gọi MISA: {review['error']}")
        continue
    for req in review['requests']:
        state = f"HĐ {req['inv_no']}" if req['inv_no'] else 'chưa phát hành'
        print(f"      đề nghị {req['refno']} {state}: {money(req['amount'])}"
              + (f" — {'; '.join(req['notes'])}" if req['notes'] else ''))
    for line in review['customs']:
        print(f"      HĐ hải quan {line['invoice_no']} [{line['item']}] SL {line['qty']:g} {money(line['amount'])} ({line['state']})")
    if not review['requests'] and not review['customs']:
        print("      MISA không có đề nghị / HĐ hải quan nào cho đơn này")
    for reason in review['reasons'] or ['unexplained']:
        detail = ', '.join(review.get(DETAIL_KEYS.get(reason, ''), []) or [])
        if reason == 'duplicate_request':
            detail = '; '.join(', '.join(refno for refno, _inv in d['requests']) + f" cùng {money(d['amount'])}"
                               for d in review['duplicates'])
        label = REASON_LABELS.get(reason, 'Mặt hàng khớp — lệch do chia tiền giữa các phiếu / đơn gộp')
        print(f"      ⇒ {label}" + (f": {detail}" if detail else ''))
        reason_count[label] += 1
    if review['refresh_fixes']:
        refresh_fixes.append(row['name'])

print(f"\n{SEP}\n  CẶP ĐƠN CÙNG KHÁCH LỆCH NGƯỢC DẤU (hàng đơn thiếu nằm trên HĐ đơn thừa)")
for short, over, amount in scope['pairs'] or []:
    print(f"    {short} thiếu ⇄ {over} thừa {money(amount)} → soát lại theo đơn cả 2 (đã thêm vào ORDERS); vẫn lệch"
          " thì xem HĐ, đúng hàng đơn thiếu thì gắn tay đề nghị cho phiếu của nó")
    refresh_fixes += [name for name in (short, over) if name not in refresh_fixes]
if not scope['pairs']:
    print("    (không có)")

print(f"\n{SEP}\n  TỔNG HỢP LÝ DO")
for reason, count in sorted(reason_count.items(), key=lambda kv: -kv[1]):
    print(f"    {count:>4} đơn — {reason}")
print(f"\n  {len(refresh_fixes)} đơn SOÁT LẠI THEO ĐƠN là tự sửa — dán vào ORDERS của bin/fix_misa_invoice_reassign_orders.py:")
print(f"    ORDERS = {refresh_fixes!r}")
print(SEP)
