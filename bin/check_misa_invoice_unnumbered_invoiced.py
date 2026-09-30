# -*- coding: utf-8 -*-
"""
check_misa_invoice_unnumbered_invoiced.py
=========================================
460 phiếu đang "Đã xuất HĐ" mà KHÔNG có số hóa đơn — xem MISA thật sự trả gì cho chúng trước khi
sửa, để không hạ nhầm phiếu đã xuất HĐ thật về "chờ HĐ".

Các phiếu này đi đường dự phòng _misa_invoice_result_from_request_by_customer: dòng đề nghị
(sa_invoice_request) không có cột inv_no → tải hóa đơn (sa_invoice_get) theo tên khách, lấy
hóa đơn trỏ về đề nghị (sa_invoice_request_refid). Hai khả năng, script phân biệt được:
  A. Hóa đơn tìm ra KHÔNG có số (inv_no trống) và trạng thái phát hành là chưa → hóa đơn nháp,
     phiếu KHÔNG được coi là đã xuất HĐ (case KBC/OUT/13489).
  B. Hóa đơn đã phát hành nhưng dòng sa_invoice_get không mang số ở cột inv_no (tên cột khác)
     → phiếu đúng là đã xuất HĐ, chỉ là đọc số HĐ sai cột — sửa chỗ đọc số, KHÔNG hạ phiếu.

Với SAMPLE phiếu (luôn gồm ALWAYS), in: dòng đề nghị có cột inv_no không; các hóa đơn khớp và
MỌI cột của hóa đơn đầu tiên (để thấy cột số HĐ / trạng thái phát hành tên là gì).

CHỈ ĐỌC — không write/create/unlink gì. Có gọi API MISA (đọc).

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_misa_invoice_unnumbered_invoiced.py
"""

SAMPLE = 8
ALWAYS = ['KBC/OUT/13489', 'KBC/OUT/12537', 'KBC/OUT/13249']
SEP = "=" * 100
INVOICE_URL = "https://actapp.misa.vn/g2/api/sa/v1/sa_invoice_get/paging_filter_v2"
INTERESTING = ('inv', 'publish', 'status', 'refno', 'total_amount', 'einvoice', 'sign')

Picking = env['stock.picking'].sudo()
misa = env['misa.api.utils'].sudo()
config = env['misa.config'].sudo()


def money(v):
    return f"{(v or 0.0):,.0f}".replace(",", ".")


pickings = Picking.search([
    ('misa_invoice_state', '=', 'invoiced'), ('misa_invoice_master_picking_id', '=', False),
    ('misa_invoice_request_refid', '!=', False), '|', ('misa_invoice_no', '=', False), ('misa_invoice_no', '=', ''),
], order='date_done desc')
sample = pickings.filtered(lambda p: p.name in ALWAYS) | pickings.filtered(lambda p: p.name not in ALWAYS)[:SAMPLE]
print(f"\n{SEP}\n  {len(pickings)} phiếu 'Đã xuất HĐ' không số HĐ — soát {len(sample)} phiếu mẫu\n{SEP}")

printed_keys = False
for picking in sample:
    refno, refid = picking.misa_invoice_request_refno, picking.misa_invoice_request_refid
    print(f"\n  {picking.name} ({', '.join(picking.misa_invoice_sale_order_ids.mapped('name'))})"
          f" XK {money(picking.misa_invoice_net_actual_amount)} | tiền HĐ đang ghi {money(picking.misa_invoice_amount)}"
          f" | đề nghị {refno}")
    try:
        rows = misa.get_invoice_requests_for_order(refno) if refno else []
        payload = config.get_invoice_request_payload(refno) if refno else None
        raw_req = []
        if payload:
            data = misa._fetch_misa_json_with_session_retry(
                "https://actapp.misa.vn/g2/api/sa/v1/sa_invoice_request/paging_filter_v2", payload, "sa_invoice_request (soát)",
            )
            raw_req = [r for r in (data.get("Data", {}).get("PageData", []) or []) if r.get('refid') == refid]
        if not raw_req:
            print(f"      ⚠️ không tìm lại được đề nghị refid {refid} (tìm theo số đề nghị ra {len(rows)} đề nghị)")
            continue
        req = raw_req[0]
        print(f"      đề nghị: có cột inv_no = {'inv_no' in req}"
              f" | inv_no = {req.get('inv_no')!r} | khách {req.get('account_object_name')!r}")
        customer = req.get('account_object_name')
        invoices = misa._fetch_misa_json_with_session_retry(
            INVOICE_URL, config.get_invoice_full_search_payload(customer), "sa_invoice_get (soát)",
        ).get("Data", {}).get("PageData", []) or []
        matched = [inv for inv in invoices if inv.get('sa_invoice_request_refid') == refid]
        print(f"      hóa đơn của khách tải được: {len(invoices)} | trỏ về đề nghị này: {len(matched)}")
        for inv in matched:
            picked = {k: v for k, v in inv.items() if any(t in k.lower() for t in INTERESTING)}
            print(f"        {picked}")
        if matched and not printed_keys:
            printed_keys = True
            print(f"      MỌI cột của hóa đơn đầu tiên: {sorted(matched[0].keys())}")
    except Exception as e:
        print(f"      ❌ lỗi gọi MISA: {e}")

print(f"\n{SEP}")
print("  Gửi lại kết quả: tôi cần xem cột số HĐ / trạng thái phát hành của hóa đơn khớp để biết phiếu nào\n"
      "  là hóa đơn nháp (hạ về 'chờ HĐ'), phiếu nào đã phát hành (chỉ sửa chỗ đọc số HĐ).")
print(SEP)
