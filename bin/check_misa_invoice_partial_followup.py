# -*- coding: utf-8 -*-
"""
check_misa_invoice_partial_followup.py
======================================
Vì sao phiếu xuất kho ĐỢT SAU của 1 đơn báo "Đã xuất hóa đơn" trong khi HĐ chỉ phủ đợt trước —
và kiểm từng phiếu bin/fix_misa_invoice_own_order_overmatch.py định GỠ ăn theo có đúng không.

Case gốc: DH125524949235092 bán 10 cái — KBC/OUT/11995 (13/08) xuất 8 cái, có HĐ 00004909;
KBC/OUT/14143 (15/10) xuất thêm 2 cái, chưa lập đề nghị — vậy mà 14143 báo "Đã xuất HĐ" ăn theo
11995. Nguyên nhân: khớp dòng hàng đề nghị của 11995 loại hẳn 11995 khỏi FIFO, nên 2/8 cái của
dòng (vốn của 11995) khớp sang 14143.

Phiếu bị gỡ ăn theo sẽ được KIỂM TRA LẠI MISA ngay — nên với mỗi phiếu trong PICKING_NAMES in:
  - đơn: SL đã xuất kho (mọi phiếu) so với SL HĐ ĐÃ PHÁT HÀNH theo từng mã hàng (thiếu mã nào);
  - SAU KHI GỠ phiếu sẽ nhận gì: đề nghị mang đúng tên phiếu, không có thì đề nghị tìm theo mã đơn
    (bỏ đề nghị mang tên / đang thuộc phiếu khác cùng đơn — luật mới của module).
Đơn đủ HĐ mà phiếu sau khi gỡ KHÔNG nhận được đề nghị nào → ⚠️ cần xem (gỡ xong sẽ báo thiếu HĐ).
DETAIL = True in thêm phiếu / dòng gộp / dòng đề nghị để đọc tay (mặc định chỉ in ca ⚠️).

CHỈ ĐỌC — không write/create/unlink gì. Có gọi API MISA (đọc).

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    cd ~/src/user
    odoo-bin shell -d <TEN_DATABASE> < bin/check_misa_invoice_partial_followup.py
"""

from collections import defaultdict

# Danh sách gỡ ăn theo của lần chạy thử fix_misa_invoice_own_order_overmatch.py (staging 19/10).
PICKING_NAMES = [
    'KBC/OUT/06142', 'KBC/OUT/08016', 'KBC/OUT/08541', 'KBC/OUT/09195', 'KBC/OUT/09479',
    'KBC/OUT/10348', 'KBC/OUT/10574', 'KBC/OUT/11686', 'KBC/OUT/11749', 'KBC/OUT/12644',
    'KBC/OUT/12690', 'KBC/OUT/12704', 'KBC/OUT/13092', 'KBC/OUT/13410', 'KBC/OUT/13471',
]
DETAIL = False
QTY_EPS = 0.001
SEP = "=" * 100

Picking = env['stock.picking'].sudo()
misa = env['misa.api.utils']


def order_pickings(order):
    return Picking.search([
        ('misa_invoice_sale_order_ids', '=', order.id), ('picking_type_id.code', '=', 'outgoing'),
        ('state', '=', 'done'),
    ], order='date_done, id')


def shipped_by_item(pickings):
    shipped = defaultdict(float)
    for p in pickings:
        for m in p.move_ids_without_package.filtered(lambda m: m.state == 'done'):
            shipped[(m.product_id.default_code or '').strip().upper()] += m.quantity
    return shipped


def order_requests(order, pickings):
    """Mọi đề nghị nhắc mã đơn, cộng đề nghị tìm theo tên từng phiếu — {refid: {refno, inv_no}}."""
    requests = {r['refid']: r for r in misa.get_invoice_requests_for_order(order.name)}
    for p in pickings:
        status = misa.get_invoice_status_for_refno(p.name)
        if status.get('request_refid') and status['request_refid'] not in requests:
            requests[status['request_refid']] = {
                'refno': status.get('master_refno') or '', 'refid': status['request_refid'],
                'inv_no': status.get('invoice_no') or '',
            }
    return requests


def invoiced_by_item(order, requests):
    """SL HĐ đã phát hành theo mã hàng (chỉ dòng ghi đúng mã đơn), kèm dòng để in chi tiết."""
    invoiced, detail = defaultdict(float), []
    for req in requests.values():
        for line in misa.get_invoice_request_lines(req['refid']):
            code = (line.get('inventory_item_code') or '').strip().upper()
            own = (line.get('order_code') or '').strip() == order.name
            if own and req['inv_no'] and code:
                invoiced[code] += line.get('quantity') or 0.0
            if code:
                detail.append(f"đề nghị {req['refno']} ({req['inv_no'] or 'chưa phát hành'}): "
                              f"{line.get('order_code') or '(trống mã đơn)'} [{code}] SL {line.get('quantity') or 0:g}")
    return invoiced, detail


def print_detail(pickings, detail):
    for p in pickings:
        items = ', '.join(f"{m.product_id.default_code}×{m.quantity:g}" for m in p.move_ids_without_package
                          if m.state == 'done')
        print(f"      {p.name} ({p.date_done:%d/%m}) {items} | {p.misa_invoice_state} | đề nghị "
              f"{p.misa_invoice_request_refno or '—'} | ăn theo {p.misa_invoice_master_picking_id.name or '—'}")
        for match in p.misa_invoice_grouped_match_ids:
            print(f"        khớp dòng gộp của {match.line_id.master_picking_id.name}: "
                  f"[{match.line_id.inventory_item_code}] {match.quantity:g}/{match.line_id.quantity:g}")
    for row in detail:
        print(f"      {row}")


def status_after_release(picking):
    """Đề nghị phiếu nhận khi kiểm tra lại sau khi gỡ — cùng thứ tự với action_check_misa_invoice_status:
    theo tên phiếu trước, không ra thì theo mã đơn (bỏ đề nghị của phiếu khác cùng đơn).
    Trả (status, 'tên phiếu' | 'mã đơn' | '')."""
    status = misa.get_invoice_status_for_refno(picking.name)
    if status['state'] != 'missing':
        return status, 'tên phiếu'
    siblings = picking._misa_invoice_sibling_pickings()
    for order in picking.misa_invoice_sale_order_ids:
        status, _skipped = misa.get_invoice_status_for_order(
            order.name, skip_refnos=set(siblings.mapped('name')),
            skip_refids={r for r in siblings.mapped('misa_invoice_request_refid') if r},
        )
        if status['state'] != 'missing':
            return status, 'mã đơn'
    return status, ''


verdicts = defaultdict(list)
for picking in Picking.search([('name', 'in', PICKING_NAMES)], order='name'):
    order = picking.misa_invoice_sale_order_ids[:1]
    pickings = order_pickings(order)
    shipped = shipped_by_item(pickings)
    invoiced, detail = invoiced_by_item(order, order_requests(order, pickings))
    short = {code: qty - invoiced.get(code, 0.0) for code, qty in shipped.items()
             if qty - invoiced.get(code, 0.0) > QTY_EPS}
    after, via = status_after_release(picking)
    gets = (f"nhận đề nghị {after['master_refno']} theo {via} ({after['state']}, HĐ {after.get('invoice_no') or '—'})"
            if via else 'KHÔNG nhận đề nghị nào')
    # Đơn còn thiếu HĐ mà phiếu không nhận gì là đúng (báo thiếu thật); đơn đủ HĐ mà không nhận gì
    # thì gỡ xong phiếu báo thiếu HĐ dù đã xuất — phải đọc tay.
    verdict = 'cần xem' if not short and not via else 'ổn'
    verdicts[verdict].append(picking.name)
    gap = ', '.join(f"{code} thiếu {qty:g}" for code, qty in short.items()) or 'đơn đủ HĐ'
    print(f"\n  {'⚠️' if verdict == 'cần xem' else '✅'} {picking.name} — {order.name} {order.partner_id.display_name[:35]}"
          f" | {gap} | sau khi gỡ: {gets}")
    if DETAIL or verdict == 'cần xem':
        print_detail(pickings, detail)

print(f"\n{SEP}")
for verdict, names in verdicts.items():
    print(f"  {verdict}: {len(names)} — {', '.join(names)}")
missing = set(PICKING_NAMES) - set(Picking.search([('name', 'in', PICKING_NAMES)]).mapped('name'))
if missing:
    print(f"  Không thấy phiếu: {', '.join(sorted(missing))}")
print(SEP)
