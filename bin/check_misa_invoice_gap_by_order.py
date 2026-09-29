# -*- coding: utf-8 -*-
"""
check_misa_invoice_gap_by_order.py
==================================
Kế toán nói "đã xuất HĐ đủ" nhưng khung "Vì sao còn lệch" vẫn báo thiếu — script này hỏi
THẲNG MISA theo TỪNG ĐƠN HÀNG để biết ai đúng.

Với mỗi đơn hàng của các phiếu đang lệch (lấy đúng danh sách khung "Vì sao còn lệch" đang
hiện, qua get_misa_invoice_gap_analysis — không chép lại công thức):
  - Phía Odoo : tiền xuất kho của MỌI phiếu đã done thuộc đơn (không giới hạn khoảng ngày),
                và tiền HĐ Odoo đang quy về các phiếu đó (misa_invoice_allocated_amount).
  - Phía MISA : MỌI đề nghị xuất HĐ có nhắc tới mã đơn (ai lập cũng được, tên đề nghị là gì
                cũng được), cộng tiền CÓ VAT các dòng hàng ghi đúng mã đơn này. Tách riêng
                đề nghị ĐÃ phát hành HĐ (có số HĐ) và đề nghị CHƯA phát hành. Cộng thêm HĐ
                hải quan đã ghi nhận ở tab Đơn hải quan (loại này xuất thẳng, không qua đề
                nghị nên tìm đề nghị theo mã đơn không ra).

Kết luận từng đơn:
  [A] MISA ĐỦ, Odoo báo THIẾU  -> lỗi đối soát bên Odoo (khớp sai/thiếu đề nghị). In ra các
                                  đề nghị mà Odoo chưa gắn vào phiếu nào.
  [B] MISA cũng THIẾU          -> thiếu thật, gửi kế toán kèm số tiền + đề nghị đang có.
  [C] MISA THỪA                -> HĐ nhiều hơn xuất kho (hàng trả chưa điều chỉnh, gộp nhầm).
  [D] MISA không có đề nghị nào ghi mã đơn này -> nếu kế toán nói đã xuất thì HĐ được lập
                                  KHÔNG ghi mã đơn (hoặc xuất thẳng không qua đề nghị) — cần
                                  xin số HĐ để gắn tay.
  [E] Cả 2 bên đều ĐỦ          -> đơn không thiếu, phần lệch chỉ là cách Odoo chia tiền giữa
                                  các phiếu/đơn trong 1 đề nghị gộp.

CHỈ ĐỌC — không write/create/unlink gì. Có gọi API MISA (đọc), không đổi gì bên MISA.

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_misa_invoice_gap_by_order.py
"""

from collections import defaultdict

# ---- Sửa ở đây -----------------------------------------------------------------------------
SALER_CODE = ''                 # BẮT BUỘC: mã sale đang xem trên trang /misa_sale_status
DATE_FROM = False               # 'YYYY-MM-DD' ngày xuất kho, False = từ mốc đối soát
DATE_TO = False
# Nhóm lý do cần soát (key như khung "Vì sao còn lệch").
CATEGORIES = ('invoice_short', 'invoice_over', 'partial_elsewhere', 'no_invoice')
ONLY_ORDERS = []                # để trống = mọi đơn; hoặc ['DH125524949232207', ...] để soát vài đơn
MAX_ORDERS = 150                # chặn trên số đơn (mỗi đơn tốn 1 + số đề nghị lệnh gọi MISA)
TOLERANCE = 1000.0              # đ — lệch dưới mức này coi như khớp (làm tròn VAT theo dòng)
# ---------------------------------------------------------------------------------------------

URL_REQ = "https://actapp.misa.vn/g2/api/sa/v1/sa_invoice_request/paging_filter_v2"
REQUEST_SEARCH_PAGE_SIZE = 10   # get_invoice_request_payload chỉ lấy 1 trang 10 dòng

SEP = "=" * 100
SUB = "-" * 100

Picking = env['stock.picking'].sudo()
SaleOrder = env['sale.order'].sudo().with_context(active_test=False)
misa = env['misa.api.utils'].sudo()
cfg = env['misa.config'].sudo()


def money(v):
    return f"{(v or 0.0):,.0f}".replace(",", ".")


def picking_orders(picking):
    group = picking | picking.misa_invoice_covered_picking_ids
    return group.mapped('misa_invoice_sale_order_ids')


# ---- 1. Danh sách phiếu đang lệch: đúng cái khung đang hiện ---------------------------------
if not SALER_CODE:
    raise SystemExit("Điền SALER_CODE ở đầu script (mã sale đang xem trên trang) rồi chạy lại.")
print(f"\n{SEP}\n  SOÁT LỆCH XUẤT HĐ THEO ĐƠN HÀNG — sale {SALER_CODE!r}, xuất kho {DATE_FROM or 'mốc'} → {DATE_TO or 'nay'}\n{SEP}")
analysis = Picking.get_misa_invoice_gap_analysis(
    date_from=DATE_FROM, date_to=DATE_TO, saler_code=SALER_CODE, limit=100000,
)
print(f"  Khung 'Vì sao còn lệch' đang báo: {money(analysis['outstanding_amount'])} đ")
for cat in analysis['categories']:
    print(f"    - {cat['label']:<32} {money(cat['amount']):>16} đ  ({cat['count']})")

rows = [r for r in analysis['rows'] if r['source'] == 'misa' and r['category'] in CATEGORIES]
gap_by_picking = {r['id']: r for r in rows}
orders = SaleOrder.browse()
for picking in Picking.browse(list(gap_by_picking)):
    orders |= picking_orders(picking)
if ONLY_ORDERS:
    orders = orders.filtered(lambda o: o.name in ONLY_ORDERS)
orders = orders.sorted('name')
print(f"\n  {len(rows)} phiếu lệch thuộc nhóm {CATEGORIES} → {len(orders)} đơn hàng cần hỏi MISA"
      + (f" (chỉ soát {MAX_ORDERS} đơn đầu)" if len(orders) > MAX_ORDERS else ""))
orders = orders[:MAX_ORDERS]


# ---- 2. Hỏi MISA ---------------------------------------------------------------------------
_lines_cache = {}


def request_lines(refid):
    """Dòng hàng của 1 đề nghị — cache vì 1 đề nghị gộp được nhiều đơn cùng nhắc tới."""
    if refid not in _lines_cache:
        _lines_cache[refid] = misa.get_invoice_request_lines(refid)
    return _lines_cache[refid]


def requests_for_order(order_name):
    """Dòng đề nghị ĐẦY ĐỦ (còn giữ inv_no) — get_invoice_requests_for_order chỉ trả refno/refid."""
    data = misa._fetch_misa_json_with_session_retry(
        URL_REQ, cfg.get_invoice_request_payload(order_name), "sa_invoice_request (theo đơn %s)" % order_name,
    )
    return [item for item in (data.get("Data", {}).get("PageData", []) or []) if item.get('refid')]


def odoo_known_refids():
    """Mọi request_refid Odoo đã gắn vào phiếu nào đó (tự khớp, gắn tay, hoặc qua dòng gộp)."""
    known = set(Picking.search([('misa_invoice_request_refid', '!=', False)]).mapped('misa_invoice_request_refid'))
    known |= set(env['misa.invoice.grouped.line'].sudo().search([]).mapped('request_refid'))
    return known


KNOWN_REFIDS = odoo_known_refids()
results = []

for order in orders:
    order_pickings = Picking.search([
        ('misa_invoice_sale_order_ids', '=', order.id),
        ('picking_type_id.code', '=', 'outgoing'),
        ('state', '=', 'done'),
    ])
    shipped = sum(order_pickings.mapped('misa_invoice_net_actual_amount'))
    odoo_alloc = sum(order_pickings.mapped('misa_invoice_allocated_amount'))

    try:
        reqs = requests_for_order(order.name)
    except Exception as e:
        print(f"\n  ❌ {order.name}: lỗi tìm đề nghị trên MISA: {type(e).__name__}: {e}")
        continue

    issued, pending, req_info = 0.0, 0.0, []
    for item in reqs:
        refid = item['refid']
        try:
            lines = request_lines(refid)
        except Exception as e:
            req_info.append({'refno': item.get('refno'), 'error': f"{type(e).__name__}: {e}"})
            continue
        own = [ln for ln in lines if (ln.get('order_code') or '').strip() == order.name]
        no_code = [ln for ln in lines if not (ln.get('order_code') or '').strip()]
        amount = Picking._misa_invoice_request_line_amount(own)
        inv_no = (item.get('inv_no') or '').strip()
        if inv_no:
            issued += amount
        else:
            pending += amount
        req_info.append({
            'refno': (item.get('refno') or '').strip(), 'refid': refid, 'inv_no': inv_no,
            'inv_date': item.get('inv_date'), 'amount': amount, 'own_lines': len(own), 'all_lines': len(lines),
            'no_code_amount': Picking._misa_invoice_request_line_amount(no_code), 'no_code_lines': len(no_code),
            'known': refid in KNOWN_REFIDS,
        })

    # Hóa đơn hải quan xuất thẳng, không qua đề nghị — tìm đề nghị theo mã đơn không bao giờ ra,
    # phải cộng từ các dòng đã ghi nhận ở tab Đơn hải quan.
    customs_lines = env['misa.invoice.customs.line'].sudo().search([('sale_order_id', '=', order.id)])
    customs_amount = sum(customs_lines.mapped('amount'))
    issued += customs_amount
    customs_info = []
    for inv_no in sorted(set(customs_lines.mapped('invoice_no'))):
        inv_lines = customs_lines.filtered(lambda l, inv_no=inv_no: l.invoice_no == inv_no)
        customs_info.append({
            'invoice_no': inv_no,
            'amount': sum(inv_lines.mapped('amount')),
            # Bản module cũ chưa có field này = mọi dòng đều đang lưu tiền chưa VAT.
            'vat': all(getattr(line, 'amount_includes_vat', False) for line in inv_lines),
        })

    if not reqs and not customs_lines:
        verdict = 'D'
    elif abs(issued - shipped) <= TOLERANCE:
        verdict = 'E' if abs(odoo_alloc - shipped) <= TOLERANCE else 'A'
    elif issued < shipped:
        verdict = 'B'
    else:
        verdict = 'C'
    results.append({
        'order': order, 'pickings': order_pickings, 'shipped': shipped, 'odoo_alloc': odoo_alloc,
        'issued': issued, 'pending': pending, 'reqs': req_info, 'customs': customs_info, 'verdict': verdict,
        'truncated': len(reqs) >= REQUEST_SEARCH_PAGE_SIZE,
    })


# ---- 3. In kết quả -------------------------------------------------------------------------
VERDICT_LABEL = {
    'A': "[A] MISA ĐỦ — Odoo báo THIẾU (lỗi đối soát Odoo)",
    'B': "[B] MISA cũng THIẾU (thiếu thật)",
    'C': "[C] MISA THỪA so với xuất kho",
    'D': "[D] MISA KHÔNG có đề nghị / HĐ hải quan nào ghi mã đơn này",
    'E': "[E] Cả 2 bên ĐỦ theo đơn — lệch chỉ do chia tiền giữa các phiếu",
}

by_verdict = defaultdict(list)
for res in results:
    by_verdict[res['verdict']].append(res)

for key in 'ABCDE':
    items = by_verdict.get(key, [])
    if not items:
        continue
    print(f"\n{SEP}\n  {VERDICT_LABEL[key]}: {len(items)} đơn\n{SEP}")
    for res in items:
        order = res['order']
        print(f"\n  ▸ {order.name}  ({order.partner_id.commercial_partner_id.name or '-'})")
        print(f"      Xuất kho (Odoo, mọi phiếu done): {money(res['shipped']):>15} đ   "
              f"HĐ Odoo đang quy về: {money(res['odoo_alloc']):>15} đ")
        print(f"      MISA đã phát hành HĐ           : {money(res['issued']):>15} đ   "
              f"MISA đề nghị chưa phát hành: {money(res['pending']):>11} đ   "
              f"→ MISA − xuất kho = {money(res['issued'] - res['shipped'])} đ")
        for p in res['pickings']:
            mark = ' ← đang lệch' if p.id in gap_by_picking else ''
            print(f"        phiếu {p.name:<16} {str(p.date_done)[:10]}  XK {money(p.misa_invoice_net_actual_amount):>13}"
                  f"  HĐ quy về {money(p.misa_invoice_allocated_amount):>13}  state={p.misa_invoice_state}"
                  f"  đề nghị={p.misa_invoice_request_refno or '-'}{mark}")
        for r in res['reqs']:
            if 'error' in r:
                print(f"        đề nghị {r['refno']!r}: ❌ lỗi đọc dòng hàng {r['error']}")
                continue
            flags = []
            if not r['known']:
                flags.append('ODOO CHƯA GẮN')
            if r['no_code_lines']:
                flags.append(f"{r['no_code_lines']} dòng KHÔNG ghi mã đơn = {money(r['no_code_amount'])} đ")
            print(f"        đề nghị {r['refno']:<18} HĐ {r['inv_no'] or '(chưa phát hành)':<12}"
                  f" dòng của đơn {r['own_lines']}/{r['all_lines']} = {money(r['amount']):>13} đ"
                  + (f"   ⚠️ {'; '.join(flags)}" if flags else ''))
        for c in res['customs']:
            print(f"        HĐ hải quan {c['invoice_no']:<12} dòng của đơn = {money(c['amount']):>13} đ"
                  + ("" if c['vat'] else "   ⚠️ tiền CHƯA VAT — cron hải quan chưa đọc lại hóa đơn này từ MISA"))
        if res['truncated']:
            print(f"        ⚠️ MISA trả đủ {REQUEST_SEARCH_PAGE_SIZE} đề nghị (trần 1 trang) — có thể còn đề nghị chưa đọc tới.")

print(f"\n{SEP}\n  TỔNG KẾT\n{SEP}")
for key in 'ABCDE':
    items = by_verdict.get(key, [])
    if items:
        short = sum(res['shipped'] - res['issued'] for res in items)
        odoo_short = sum(res['shipped'] - res['odoo_alloc'] for res in items)
        print(f"  {VERDICT_LABEL[key]:<62} {len(items):>4} đơn | "
              f"Odoo báo thiếu {money(odoo_short):>14} đ | MISA thiếu {money(short):>14} đ")
print(
    "\n  Đọc kết quả:\n"
    "    [A] đưa lại cho dev: Odoo chưa gắn/khớp đúng đề nghị (xem dòng 'ODOO CHƯA GẮN').\n"
    "    [B] gửi kế toán: đơn còn thiếu đúng số 'MISA − xuất kho' (số âm).\n"
    "    [D] nếu kế toán nói đã xuất: xin số HĐ, HĐ đó không ghi mã đơn nên Odoo không tìm ra.\n"
    "    'dòng KHÔNG ghi mã đơn' trong đề nghị cũng là lý do Odoo không cộng được tiền cho đơn."
)
print(SEP)
