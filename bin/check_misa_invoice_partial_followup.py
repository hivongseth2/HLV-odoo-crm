# -*- coding: utf-8 -*-
"""
check_misa_invoice_partial_followup.py
======================================
Vì sao phiếu xuất kho ĐỢT SAU của 1 đơn báo "Đã xuất hóa đơn" trong khi HĐ chỉ phủ đợt trước.

Case: DH125524949235092 bán 10 cái — KBC/OUT/11995 (13/08) xuất 8 cái, có HĐ 00004909
31.104.000 đ; KBC/OUT/14143 (15/10) xuất thêm 2 cái, chưa lập đề nghị — vậy mà 14143 báo
"Đã xuất HĐ", số HĐ 00004909, gộp chung với phiếu gốc 11995.

Nghi vấn (đọc code stock_picking.py):
  1. Kiểm tra 14143: tra theo tên phiếu không ra → thử theo MÃ ĐƠN → ra đề nghị của 11995
     (HĐ 00004909). claimed_order_refnos chỉ chặn trong CÙNG 1 lượt kiểm tra, 11995 đã kiểm từ
     lượt trước nên không chặn được → 14143 nhận state 'invoiced' + refid của 11995.
  2. master_refno = KBC/OUT/11995 ≠ tên phiếu → buộc 11995 quét lại đơn xuất kèm
     (_misa_invoice_discover_grouped_orders). Đơn của đề nghị là ĐƠN CHÍNH của 11995 nên
     exclude_picking_ids=[11995] → 8 cái trên đề nghị (của chính 11995) bị FIFO khớp sang
     14143 → 2/2 cái "khớp đủ" → gán 14143 ăn theo 11995.
  3. Hoặc lưới dự phòng _misa_invoice_dedupe_request_refid_groups: 2 phiếu cùng refid,
     _misa_invoice_request_covers_fully trả True khi chưa khớp dòng nào → gán ăn theo.
Script in đủ dữ liệu để biết rơi vào nhánh nào.

CHỈ ĐỌC — không write/create/unlink gì. Có gọi API MISA (đọc).

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_misa_invoice_partial_followup.py
"""

import re
from collections import defaultdict

ORDER_NAME = 'DH125524949235092'
CHATTER_LIMIT = 12          # số tin nhắn chatter gần nhất in cho mỗi phiếu
SEP = "=" * 100

Picking = env['stock.picking'].sudo()
misa = env['misa.api.utils']


def money(v):
    return f"{(v or 0.0):,.0f}".replace(",", ".")


def strip_html(html):
    return re.sub(r'<[^>]+>', '', str(html or '')).replace('&nbsp;', ' ').strip()


order = env['sale.order'].sudo().with_context(active_test=False).search([('name', '=', ORDER_NAME)], limit=1)
if not order:
    raise SystemExit(f"❌ Không thấy đơn {ORDER_NAME}")

pickings = Picking.search([
    ('misa_invoice_sale_order_ids', '=', order.id), ('picking_type_id.code', '=', 'outgoing'),
], order='date_done, id')

# ---------------------------------------------------------------- A. Odoo
print(f"\n{SEP}\n  A. ODOO — {order.name} | {order.partner_id.display_name}\n{SEP}")
for line in order.order_line.filtered(lambda l: not l.display_type):
    print(f"    [{line.product_id.default_code}] đặt {line.product_uom_qty:g} giao {line.qty_delivered:g}"
          f" | giá {money(line.price_unit)} | thuế {', '.join(line.tax_id.mapped('name'))}")
print(f"\n    Theo đơn: HĐ {money(order.misa_invoice_order_invoiced_amount)} | soát lúc {order.misa_invoice_order_checked_at}")
for src in (order.misa_invoice_order_sources or '').splitlines():
    print(f"      nguồn: {src}")

shipped = defaultdict(float)
for p in pickings:
    print(f"\n  ▸ {p.name} ({p.state}, xuất {p.date_done})")
    for m in p.move_ids_without_package.filtered(lambda m: m.state == 'done'):
        shipped[m.product_id.default_code or ''] += m.quantity
        print(f"      [{m.product_id.default_code}] SL {m.quantity:g}")
    print(f"      trạng thái {p.misa_invoice_state} | số HĐ {p.misa_invoice_no or '—'} | tiền HĐ {money(p.misa_invoice_amount)}"
          f" | thực xuất {money(p.misa_invoice_net_actual_amount)}")
    print(f"      refno đề nghị {p.misa_invoice_request_refno or '—'} | refid {p.misa_invoice_request_refid or '—'}"
          f" | gắn tay {p.misa_invoice_manual_refno or '—'}")
    print(f"      ăn theo {p.misa_invoice_master_picking_id.name or '—'} | đang làm gốc cho "
          f"{', '.join(p.misa_invoice_covered_picking_ids.mapped('name')) or '—'}"
          f" | đã quét xuất kèm {p.misa_invoice_group_checked} | khớp dòng hàng {money(p.misa_invoice_grouped_matched_amount)}")
    for match in p.misa_invoice_grouped_match_ids:
        gl = match.line_id
        print(f"      khớp dòng gộp: [{gl.inventory_item_code}] SL {match.quantity:g} / dòng {gl.quantity:g}"
              f" {money(match.amount)} — dòng của đề nghị phiếu gốc {gl.master_picking_id.name}"
              f" ({'tay' if match.is_manual else 'tự động'}, {match.matched_at})")

# Dòng gộp ghi nhận trên các phiếu gốc của đơn — khớp sang phiếu nào
masters = pickings | pickings.mapped('misa_invoice_master_picking_id')
glines = env['misa.invoice.grouped.line'].sudo().search([('master_picking_id', 'in', masters.ids)])
if glines:
    print("\n    Dòng xuất HĐ chung đã ghi nhận (misa.invoice.grouped.line):")
for gl in glines:
    targets = ', '.join(f"{m.picking_id.name}×{m.quantity:g}" for m in gl.match_ids) or 'chưa khớp'
    print(f"      gốc {gl.master_picking_id.name} | đơn {gl.order_code} [{gl.inventory_item_code}] SL {gl.quantity:g}"
          f" → {targets}")

# ---------------------------------------------------------------- B. MISA
print(f"\n{SEP}\n  B. MISA — đề nghị tìm theo mã đơn và theo tên từng phiếu\n{SEP}")
requests = {r['refid']: r for r in misa.get_invoice_requests_for_order(order.name)}
for p in pickings:
    status = misa.get_invoice_status_for_refno(p.name)
    print(f"    tra tên {p.name}: {status['state']} | đề nghị {status.get('master_refno') or '—'}"
          f" | HĐ {status.get('invoice_no') or '—'} {money(status.get('invoice_amount'))}")
    if status.get('request_refid') and status['request_refid'] not in requests:
        requests[status['request_refid']] = {'refno': status.get('master_refno') or '', 'refid': status['request_refid'],
                                             'inv_no': status.get('invoice_no') or ''}
order_status = misa.get_invoice_status_for_refno(order.name)
print(f"    tra mã đơn {order.name}: {order_status['state']} | đề nghị {order_status.get('master_refno') or '—'}"
      f" | HĐ {order_status.get('invoice_no') or '—'} {money(order_status.get('invoice_amount'))}")

invoiced = defaultdict(float)
for req in requests.values():
    print(f"\n  ▸ đề nghị {req['refno']} | HĐ {req['inv_no'] or 'CHƯA PHÁT HÀNH'} | refid {req['refid']}")
    for line in misa.get_invoice_request_lines(req['refid']):
        code = (line.get('inventory_item_code') or '').strip()
        own = (line.get('order_code') or '').strip() == order.name
        if own and req['inv_no']:
            invoiced[code] += line.get('quantity') or 0.0
        print(f"      {'' if own else '(đơn khác) '}{line.get('order_code') or '(trống mã đơn)'} [{code}]"
              f" SL {line.get('quantity') or 0:g} × {money(line.get('unit_price'))}")

# ---------------------------------------------------------------- C. Kết luận
print(f"\n{SEP}\n  C. KẾT LUẬN\n{SEP}")
for code in sorted(set(shipped) | set(invoiced)):
    flag = '' if abs(shipped[code] - invoiced[code]) < 0.001 else '  ⚠️ LỆCH'
    print(f"    [{code}] đã xuất kho {shipped[code]:g} | HĐ đã phát hành {invoiced[code]:g}{flag}")

for p in pickings.filtered(lambda p: p.misa_invoice_state == 'invoiced'):
    own_request = any(r['refno'] == p.name for r in requests.values())
    # Phiếu đã có đề nghị riêng mà VẪN ăn theo phiếu khác thì vẫn là lỗi (14143 lúc 19/10).
    if (own_request and not p.misa_invoice_master_picking_id) or p.misa_invoice_manual_refno:
        continue
    if p.misa_invoice_master_picking_id:
        how = ('khớp dòng gộp' if p.misa_invoice_grouped_match_ids
               else 'gộp dự phòng theo refid (chưa khớp dòng nào → covers_fully trả True)')
        print(f"\n    ❌ {p.name} báo 'Đã xuất HĐ' vì ĂN THEO {p.misa_invoice_master_picking_id.name} ({how}),"
              f" không có đề nghị riêng.")
    else:
        print(f"\n    ❌ {p.name} báo 'Đã xuất HĐ' qua đề nghị {p.misa_invoice_request_refno or '?'}"
              f" (tìm theo MÃ ĐƠN), không có đề nghị riêng.")
    if any(m.line_id.master_picking_id in p.misa_invoice_master_picking_id
           and m.line_id.sale_order_id == order for m in p.misa_invoice_grouped_match_ids):
        print("       → dòng hàng khớp sang phiếu này là dòng CỦA CHÍNH ĐƠN trên đề nghị phiếu gốc: discover loại"
              " phiếu gốc khỏi FIFO (exclude_picking_ids) nên SL của phiếu gốc chạy sang phiếu đợt sau.")

    print(f"\n  Chatter {p.name} (mới nhất trước):")
    for msg in p.message_ids.filtered(lambda m: m.body)[:CHATTER_LIMIT]:
        print(f"    {msg.date} — {strip_html(msg.body)[:220]}")
print(SEP)
