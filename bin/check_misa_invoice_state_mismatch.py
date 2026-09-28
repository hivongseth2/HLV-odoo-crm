# -*- coding: utf-8 -*-
"""
check_misa_invoice_state_mismatch.py
====================================
Dò vì sao trạng thái xuất hóa đơn MISA của 1 đơn bán trên Odoo KHÁC với thực tế trên MISA.

ĐÃ DÒ RA (28/09/2026, chạy trên prd) — giữ lại để lần sau khỏi dò lại từ đầu:

  1) DH125524949236062 / TSN/OUT/13874 — MISA đã phát hành HĐ 00007446 mà Odoo vẫn 'requested'.
     Nguyên nhân: tên khách trên ĐỀ NGHỊ là 'KHÁCH WEB, ZALO TT COD J&T' còn trên HÓA ĐƠN là
     'J&T Express'. Bước 2 của _misa_invoice_result_from_request tìm hóa đơn bằng cách search
     theo TÊN KHÁCH của đề nghị rồi mới lọc theo sa_invoice_request_refid → hóa đơn không bao
     giờ nằm trong tập trả về. KHÔNG phải lỗi phân trang (MISA trả 171 < trần 200), và hóa đơn
     vẫn trỏ ĐÚNG refid của đề nghị. => Xem mục [FIELD CỦA ĐỀ NGHỊ] để tìm đường lấy số hóa
     đơn thẳng từ sa_invoice_request, khỏi đi qua tên khách.

  2) DH125524949235992 / KBC/OUT/12702 — Odoo báo đã xuất HĐ đủ 1.441.800đ nhưng đề nghị
     KBC/OUT/12907 chỉ phủ 880.200đ cho đơn này (còn thiếu 561.600đ).
     Nguyên nhân: _misa_invoice_dedupe_request_refid_groups gán master_picking_id + ghi
     misa_invoice_amount = 0 cho MỌI phiếu cùng request_refid mà KHÔNG kiểm tra độ phủ.

Script in ra ĐỦ 2 phía để đối chiếu:
  - Phía Odoo: field đã lưu trên từng phiếu + dựng lại đúng dòng mà dashboard đang hiển thị
    (gọi thẳng _misa_invoice_order_row, không chép lại công thức).
  - Phía MISA: tra SỐNG lần lượt sa_invoice_request → sa_invoice_get → sa_voucher_get, in cả
    số lượng bản ghi trả về để thấy ngay khi kết quả bị CẮT do phân trang.

CHỈ ĐỌC — không write/create/unlink gì. Có gọi API MISA (GET dữ liệu), không đổi gì bên MISA.

Chạy bằng lệnh (trên Odoo.sh shell):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_misa_invoice_state_mismatch.py

Sửa TARGETS bên dưới nếu muốn dò đơn khác. expect_inv_no là số hóa đơn NHÌN THẤY trên MISA
(để trống nếu chưa biết) — dùng để kiểm chứng xem bước sa_invoice_get có tìm ra nó không.
"""

TARGETS = [
    {'order': 'DH125524949236062', 'expect_inv_no': '00007446'},
    {'order': 'DH125524949235992', 'expect_inv_no': ''},
]

URL_REQ = "https://actapp.misa.vn/g2/api/sa/v1/sa_invoice_request/paging_filter_v2"
URL_INV = "https://actapp.misa.vn/g2/api/sa/v1/sa_invoice_get/paging_filter_v2"

SEP = "=" * 100
SUB = "-" * 100


def section(t):
    print(f"\n{SEP}\n  {t}\n{SEP}")


def sub(t):
    print(f"\n{SUB}\n  {t}\n{SUB}")


def money(v):
    return f"{(v or 0.0):,.0f}".replace(",", ".")


def norm_inv(v):
    """Bỏ số 0 đứng đầu để so số hóa đơn: MISA trả '00007446', người dùng gõ '7446'."""
    return (v or '').strip().lstrip('0') or ''


# Bản module đang chạy trên server có thể CŨ HƠN code trong repo (thiếu field mới thêm về
# sau). Script chẩn đoán mà chết vì AttributeError giữa chừng là vô dụng — đọc field qua 2 hàm
# dưới đây để field thiếu chỉ hiện "(chưa có field)" và chạy tiếp.
NO_FIELD = '(chưa có field trên bản module đang chạy)'


def f(rec, name):
    """Giá trị field, hoặc NO_FIELD nếu bản module trên server chưa có field đó."""
    return getattr(rec, name, NO_FIELD)


def fmoney(rec, name):
    """Như f() nhưng định dạng tiền; field thiếu thì trả nguyên chú thích."""
    v = getattr(rec, name, NO_FIELD)
    return v if v is NO_FIELD else f"{money(v)} đ"


misa = env['misa.api.utils'].sudo()
cfg = env['misa.config'].sudo()
Picking = env['stock.picking'].sudo()


def dump_odoo_side(order):
    """Mọi field MISA đã lưu trên đơn + từng phiếu, và dòng dashboard dựng lại từ chính chúng."""
    sub("A. PHÍA ODOO — dữ liệu đã lưu")
    print(f"  sale.order #{order.id} {order.name!r}")
    print(f"    amount_total                      = {money(order.amount_total)} đ")
    print(f"    misa_invoice_exact_checked_at     = {f(order, 'misa_invoice_exact_checked_at')!r}")
    print(f"    misa_invoice_exact_shipped_amount = {fmoney(order, 'misa_invoice_exact_shipped_amount')}")
    print(f"    misa_invoice_exact_invoiced_amount= {fmoney(order, 'misa_invoice_exact_invoiced_amount')}")

    pickings = order.misa_invoice_picking_ids
    print(f"\n  Phiếu xuất kho liên quan: {len(pickings)}")
    for p in pickings:
        print(f"\n    ▸ {p.name} (#{p.id}) picking_state={p.state!r}")
        print(f"        misa_invoice_state          = {f(p, 'misa_invoice_state')!r}")
        print(f"        misa_invoice_last_checked   = {f(p, 'misa_invoice_last_checked')!r}")
        print(f"        misa_invoice_request_refno  = {f(p, 'misa_invoice_request_refno')!r}")
        print(f"        misa_invoice_request_refid  = {f(p, 'misa_invoice_request_refid')!r}")
        print(f"        misa_invoice_manual_refno   = {f(p, 'misa_invoice_manual_refno')!r}")
        print(f"        misa_invoice_no / date      = {f(p, 'misa_invoice_no')!r} / {f(p, 'misa_invoice_date')!r}")
        print(f"        misa_invoice_amount         = {fmoney(p, 'misa_invoice_amount')}")
        print(f"        misa_invoice_effective_amount = {fmoney(p, 'misa_invoice_effective_amount')}")
        print(f"        misa_invoice_net_actual_amount= {fmoney(p, 'misa_invoice_net_actual_amount')}")
        print(f"        misa_invoice_order_coverage = {f(p, 'misa_invoice_order_coverage')!r}")
        print(f"        misa_invoice_group_checked  = {f(p, 'misa_invoice_group_checked')!r}")
        master = p.misa_invoice_master_picking_id
        print(f"        master_picking (ăn theo ai) = {master.name if master else None!r}"
              f"{'  -> đơn: ' + ', '.join(master.misa_invoice_sale_order_ids.mapped('name')) if master else ''}")
        covered = p.misa_invoice_covered_picking_ids
        print(f"        covered_pickings (ai ăn theo)= {covered.mapped('name') if covered else []}")
        matches = getattr(p, 'misa_invoice_grouped_match_ids', None)
        print(f"        grouped_matched_amount      = {fmoney(p, 'misa_invoice_grouped_matched_amount')}"
              f" ({len(matches) if matches is not None else 0} lượt khớp)")
        for m in (matches or []):
            line = m.line_id
            print(f"            · khớp {money(m.amount)} đ SL={m.quantity} | mã hàng {line.inventory_item_code!r}"
                  f" | đơn {line.order_code!r} | phiếu đại diện {line.master_picking_id.name!r}"
                  f" | request_refid {line.request_refid!r}")
        # Mâu thuẫn cần soi: vừa có master_picking (nghĩa là "ăn theo ĐỦ 100%", tiền HĐ = 0)
        # vừa có grouped_match nhỏ hơn tiền thực xuất (nghĩa là chỉ phủ 1 PHẦN) — 2 cái loại
        # trừ nhau theo thiết kế, đúng cái bug _misa_invoice_dedupe_request_refid_groups gây ra.
        matched_amount = getattr(p, 'misa_invoice_grouped_matched_amount', 0.0) or 0.0
        net = getattr(p, 'misa_invoice_net_actual_amount', 0.0) or 0.0
        if master and matched_amount and matched_amount < net - 1:
            print(f"        ⚠️ MÂU THUẪN: có master_picking (ăn theo ĐỦ) nhưng chỉ khớp"
                  f" {money(matched_amount)}/{money(net)} đ -> thật ra còn thiếu"
                  f" {money(net - matched_amount)} đ")
        gap = getattr(p, 'misa_invoice_gap_summary', None)
        if gap:
            print(f"        gap_summary                 = {gap!r}")

    sub("B. PHÍA ODOO — dòng mà dashboard đang hiển thị (dựng lại bằng chính _misa_invoice_order_row)")
    try:
        row = Picking._misa_invoice_order_row(order, set(pickings.ids))
    except Exception as e:
        # Gọi hàm thật của bản module đang chạy nên lỗi ở đây CHÍNH LÀ manh mối: hàm dựng dòng
        # dashboard đang vướng field/dữ liệu nào đó — in ra rồi chạy tiếp phần tra MISA.
        print(f"    ❌ _misa_invoice_order_row LỖI: {type(e).__name__}: {e}")
        return pickings
    print(f"    state            = {row['state']!r} ({row['state_label']})")
    print(f"    exact            = {row.get('exact')}  (True = dùng misa_invoice_exact_*, False = công thức xấp xỉ)")
    print(f"    invoice_amount   = {money(row['invoice_amount'])} đ")
    print(f"    outstanding      = {money(row['outstanding_amount'])} đ")
    print(f"    partial_coverage = {row.get('partial_coverage')}   multi_request = {row.get('multi_request')}")
    print("    -> state của ĐƠN suy ra từ tập trạng thái các phiếu: "
          f"{sorted(set(pickings.mapped('misa_invoice_state')))}")
    return pickings


# Chỉ in bảng field của đề nghị ĐÚNG 1 LẦN cho cả lượt chạy — mỗi đơn gọi sa_invoice_request
# 2-3 lần, in lại mỗi lần chỉ làm output dài thêm mà không thêm thông tin gì.
_dumped_request_keys = False


def dump_request_fields(row):
    """In TOÀN BỘ field MISA trả về trên 1 dòng "Đề nghị xuất hóa đơn".

    Lý do cần: trang MISA hiển thị danh sách đề nghị CÓ SẴN cột "Số hóa đơn" và "TT phát hành
    hóa đơn", nên rất có thể API cũng trả luôn mấy field đó. Nếu đúng thì lấy số hóa đơn THẲNG
    từ đề nghị được, khỏi phải đi đường sa_invoice_get tìm theo TÊN KHÁCH — chính đường đó đang
    làm TSN/OUT/13874 đứng mãi ở "chờ HĐ" (khách trên hóa đơn 'J&T Express' khác khách trên đề
    nghị 'KHÁCH WEB, ZALO TT COD J&T').
    """
    global _dumped_request_keys
    if _dumped_request_keys or not row:
        return
    _dumped_request_keys = True
    keys = sorted(row.keys())
    print(f"\n      ===== [FIELD CỦA ĐỀ NGHỊ] toàn bộ {len(keys)} field MISA trả =====")
    for key in keys:
        print(f"        {key:44s} = {row.get(key)!r}")
    hits = [k for k in keys if any(t in k.lower() for t in ('inv', 'publish', 'status', 'tax', 'refno'))]
    print(f"      ===== {len(hits)} field nghi liên quan HÓA ĐƠN (lọc theo tên) =====")
    for key in hits:
        print(f"        {key:44s} = {row.get(key)!r}")


def dump_request_search(label, keyword):
    """Bước 1: sa_invoice_request — tra theo 1 từ khóa (tên phiếu hoặc mã đơn)."""
    print(f"\n  [sa_invoice_request] tra theo {label} = {keyword!r}")
    try:
        data = misa._fetch_misa_json_with_session_retry(
            URL_REQ, cfg.get_invoice_request_payload(keyword), "sa_invoice_request (check script)",
        )
    except Exception as e:
        print(f"      ❌ LỖI GỌI MISA: {e}")
        return []
    rows = data.get("Data", {}).get("PageData", []) or []
    print(f"      MISA trả {len(rows)} đề nghị")
    for r in rows:
        memo = (r.get('journal_memo') or '').replace('\n', ' | ')
        print(f"        · refno={r.get('refno')!r} refid={r.get('refid')!r}")
        print(f"          khách={r.get('account_object_name')!r} ngày={r.get('refdate')!r}")
        print(f"          journal_memo={memo!r}")
    if rows:
        dump_request_fields(rows[0])
    return rows


def dump_invoice_search(customer, target_refid, expect_inv_no):
    """Bước 2: sa_invoice_get — ĐÂY là bước quyết định 'requested' hay 'invoiced'.

    _misa_invoice_result_from_request chỉ đọc TRANG 1 (get_invoice_full_search_payload để
    pageSize=200, không có vòng lặp phân trang) rồi lọc client-side theo sa_invoice_request_refid.
    2 cách hỏng đều phải nhìn thấy được ở đây:
      - số dòng chạm trần 200 -> danh sách bị cắt, hóa đơn nằm ngoài trang 1;
      - tên khách trên hóa đơn KHÁC tên khách trên đề nghị -> hóa đơn không hề nằm trong tập
        trả về (case TSN/OUT/13874, đã xác nhận: 171 dòng, không chạm trần, vẫn không có).
    """
    print(f"\n  [sa_invoice_get] tra hóa đơn theo TÊN KHÁCH = {customer!r}")
    try:
        data = misa._fetch_misa_json_with_session_retry(
            URL_INV, cfg.get_invoice_full_search_payload(customer), "sa_invoice_get (check script)",
        )
    except Exception as e:
        print(f"      ❌ LỖI GỌI MISA: {e}")
        return
    rows = data.get("Data", {}).get("PageData", []) or []
    print(f"      MISA trả {len(rows)} hóa đơn"
          f"{'  ⚠️ CHẠM TRẦN pageSize=200 -> danh sách BỊ CẮT' if len(rows) >= 200 else ''}")
    if rows:
        dates = sorted([r.get('inv_date') or '' for r in rows])
        print(f"      khoảng ngày hóa đơn trả về: {dates[0]!r} .. {dates[-1]!r}")

    matched = [r for r in rows if r.get('sa_invoice_request_refid') == target_refid]
    print(f"      khớp sa_invoice_request_refid == {target_refid!r}: {len(matched)} hóa đơn"
          f"  -> code sẽ kết luận {'invoiced' if matched else 'requested (CHỜ HĐ)'}")
    for r in matched:
        print(f"        · inv_no={r.get('inv_no')!r} ngày={r.get('inv_date')!r}"
              f" tiền={money(r.get('total_amount'))} paid_type={r.get('paid_type')!r}")

    if expect_inv_no:
        hit = [r for r in rows if norm_inv(r.get('inv_no')) == norm_inv(expect_inv_no)]
        if hit:
            r = hit[0]
            print(f"      hóa đơn mong đợi {expect_inv_no!r} CÓ trong danh sách trả về:")
            print(f"        sa_invoice_request_refid = {r.get('sa_invoice_request_refid')!r}")
            print(f"        (cần == {target_refid!r} thì mới được tính là đã xuất HĐ)")
        else:
            print(f"      ⚠️ hóa đơn mong đợi {expect_inv_no!r} KHÔNG có trong danh sách trả về"
                  f" -> hoặc bị cắt do phân trang, hoặc tên khách trên hóa đơn khác tên trên đề nghị")


def dump_voucher(expect_inv_no):
    """Bước 3: sa_voucher_get — tra thẳng chứng từ theo SỐ HÓA ĐƠN, không qua đề nghị.

    Cho biết hóa đơn đó THẬT SỰ trỏ về đề nghị nào (sa_invoice_request_refid), tên khách ghi
    trên hóa đơn là gì, và phủ những đơn hàng nào — đối chiếu với bước 1 là ra ngay lý do
    không khớp.
    """
    if not expect_inv_no:
        return
    print(f"\n  [sa_voucher_get] tra thẳng theo SỐ HÓA ĐƠN = {expect_inv_no!r}")
    try:
        voucher = misa.get_voucher_by_inv_no(expect_inv_no)
    except Exception as e:
        print(f"      ❌ LỖI GỌI MISA: {e}")
        return
    if not voucher:
        print("      MISA không tìm thấy chứng từ nào")
        return
    print(f"      inv_no={voucher.get('inv_no')!r} ngày={voucher.get('inv_date')!r}"
          f" tiền={money(voucher.get('total_amount'))} paid_type={voucher.get('paid_type')!r}")
    print(f"      khách TRÊN HÓA ĐƠN = {voucher.get('account_object_name')!r}"
          f"   <= SO VỚI khách TRÊN ĐỀ NGHỊ ở bước 1")
    print(f"      sa_invoice_request_refid = {voucher.get('sa_invoice_request_refid')!r}  <= SO VỚI refid Ở BƯỚC 1")
    try:
        lines = misa.get_voucher_lines(voucher.get('refid')) or []
    except Exception as e:
        print(f"      ❌ LỖI lấy chi tiết chứng từ: {e}")
        return
    print(f"      chi tiết {len(lines)} dòng hàng:")
    for ln in lines:
        print(f"        · {ln.get('inventory_item_code')!r} SL={ln.get('quantity')}"
              f" tiền={money(ln.get('amount_oc'))} đơn={ln.get('order_code')!r}")


def dump_request_lines(refid, refno, order_name):
    """Chi tiết dòng hàng của 1 đề nghị — cho biết đề nghị đó phủ NHỮNG ĐƠN NÀO, bao nhiêu tiền.

    Đây là căn cứ để hiểu case 'gộp chung': phiếu của đơn A ăn theo đề nghị của phiếu đơn B thì
    tiền hóa đơn nhìn thấy trên đơn A là tiền của CẢ NHÓM, không phải riêng đơn A. In riêng
    phần quy cho ĐƠN ĐANG XÉT để so thẳng với tiền thực xuất.
    """
    if not refid:
        return
    print(f"\n  [sa_invoice_request/get_paging_detail] chi tiết đề nghị {refno!r} ({refid})")
    try:
        lines = misa.get_invoice_request_lines(refid) or []
    except Exception as e:
        print(f"      ❌ LỖI GỌI MISA: {e}")
        return
    by_order = {}
    for ln in lines:
        code = (ln.get('order_code') or '').strip() or '(không có mã đơn)'
        by_order.setdefault(code, {'qty': 0.0, 'amount': 0.0, 'items': []})
        by_order[code]['qty'] += ln.get('quantity') or 0.0
        by_order[code]['amount'] += (ln.get('amount_oc') or 0.0) + (ln.get('vat_amount_oc') or 0.0)
        by_order[code]['items'].append(ln.get('inventory_item_code'))
    total = sum(info['amount'] for info in by_order.values())
    print(f"      {len(lines)} dòng hàng, phủ {len(by_order)} đơn hàng, tổng {money(total)} đ:")
    for code, info in by_order.items():
        mark = '  <= ĐƠN ĐANG XÉT' if code == order_name else ''
        print(f"        · {code}: SL={info['qty']} tiền(có VAT)={money(info['amount'])} đ"
              f" mã hàng={info['items']}{mark}")
    if order_name in by_order:
        print(f"      -> đề nghị này CHỈ phủ {money(by_order[order_name]['amount'])} đ cho đơn"
              f" {order_name} (trong tổng {money(total)} đ của cả đề nghị)")


# Bản module chạy trên server lệch với code trong repo là nguyên nhân rất hay gặp của kiểu
# "đọc code thấy đúng mà chạy ra sai" — in ngay từ đầu để khỏi mất công dò nhầm chỗ.
section("0. BẢN MODULE ĐANG CHẠY TRÊN SERVER NÀY")
mod = env['ir.module.module'].sudo().search([('name', '=', 'misa_invoice_status_report')], limit=1)
print(f"  misa_invoice_status_report: state={mod.state!r} installed_version={mod.latest_version!r}")
print()
print("  Field then chốt có mặt hay không (thiếu = bản trên server cũ hơn repo):")
for model_name, field_names in [
    ('sale.order', ['misa_invoice_exact_checked_at', 'misa_invoice_exact_shipped_amount',
                    'misa_invoice_exact_invoiced_amount', 'misa_invoice_picking_ids']),
    ('stock.picking', ['misa_invoice_state', 'misa_invoice_request_refno', 'misa_invoice_no',
                       'misa_invoice_master_picking_id', 'misa_invoice_grouped_match_ids',
                       'misa_invoice_order_coverage', 'misa_invoice_gap_summary']),
]:
    existing = env[model_name].sudo()._fields
    for field_name in field_names:
        print(f"    {model_name}.{field_name:38s} {'CÓ' if field_name in existing else '❌ THIẾU'}")

for target in TARGETS:
    order_name = target['order']
    expect_inv_no = target.get('expect_inv_no') or ''
    section(f"ĐƠN {order_name}   (hóa đơn mong đợi trên MISA: {expect_inv_no or 'chưa biết'})")

    order = env['sale.order'].sudo().search([('name', '=', order_name)], limit=1)
    if not order:
        print(f"  KHÔNG tìm thấy sale.order name={order_name!r}")
        continue

    pickings = dump_odoo_side(order)

    sub("C. PHÍA MISA — tra sống từng bước")
    # Tra đúng thứ tự mà action_check_misa_invoice_status đang làm: refno = mã gắn tay hoặc tên
    # phiếu trước, không ra mới thử tới mã đơn hàng.
    keywords = [('tên phiếu', p.misa_invoice_manual_refno or p.name) for p in pickings]
    keywords.append(('mã đơn hàng', order_name))

    seen_refids = set()
    for label, keyword in keywords:
        rows = dump_request_search(label, keyword)
        if not rows:
            continue
        req = rows[0]
        refid = req.get('refid')
        if refid and refid not in seen_refids:
            seen_refids.add(refid)
            dump_invoice_search(req.get('account_object_name'), refid, expect_inv_no)
            dump_request_lines(refid, req.get('refno'), order_name)

    dump_voucher(expect_inv_no)

print(f"\n{SEP}\n  XONG — script chỉ đọc, không sửa gì.\n{SEP}")
