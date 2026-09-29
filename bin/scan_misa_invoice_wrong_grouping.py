# -*- coding: utf-8 -*-
"""
scan_misa_invoice_wrong_grouping.py
===================================
Tìm (và quét bù) các phiếu xuất kho bị gán "ăn theo" SAI — cùng loại lỗi với KBC/OUT/12702 /
đơn DH125524949235992.

BỐI CẢNH — 2 lỗi đã tìm ra ngày 28/09/2026, quét bù mỗi lỗi một kiểu:

  * Lỗi "chờ HĐ hoài" (TSN/OUT/13874): KHÔNG cần script này. Phiếu đang ở 'requested' vẫn nằm
    trong domain của cron định kỳ (_misa_invoice_scan_domain chỉ loại phiếu ĐÃ 'invoiced'), nên
    sau khi deploy bản sửa, cron 30 phút/lần tự kiểm tra lại và tự chuyển sang 'Đã xuất hóa đơn'.
    Mục 1 bên dưới chỉ đếm để theo dõi tiến độ.

  * Lỗi "gán ăn theo dù chỉ phủ 1 phần" (KBC/OUT/12702): PHẢI có script này, vì phiếu đang ở
    'invoiced' nên cron CỐ Ý bỏ qua — tự nó không bao giờ được kiểm tra lại.

Dò được THUẦN TRONG DB, không tốn lệnh gọi MISA nào: phiếu vừa có master_picking_id (nghĩa là
"ăn theo ĐỦ 100%", tiền hóa đơn ghi 0) vừa có grouped_matched_amount NHỎ HƠN tiền thực xuất
(nghĩa là đề nghị kia chỉ phủ 1 PHẦN) — hai điều đó loại trừ nhau theo thiết kế.

MẶC ĐỊNH CHỈ ĐỌC. Đổi APPLY = True mới thật sự quét bù (gọi lại action_check_misa_invoice_status
cho các phiếu tìm được; chính hàm đó chạy _misa_invoice_dedupe_request_refid_groups đã sửa nên
dữ liệu tự lành). Có gọi API MISA khi APPLY = True.

Chạy bằng lệnh (trên Odoo.sh shell):
    python odoo-bin shell -d <TEN_DATABASE> < bin/scan_misa_invoice_wrong_grouping.py
"""

APPLY = False          # True = quét bù thật; False = chỉ liệt kê
BATCH_SIZE = 20        # số phiếu mỗi lô khi quét bù (mỗi phiếu tốn vài lệnh gọi MISA)
MAX_APPLY = 200        # trần số phiếu xử lý 1 lượt chạy, tránh treo shell hàng giờ

# Sai số làm tròn khi so tiền — giữ đúng hằng số module đang dùng để 2 nơi không lệch kết luận.
TOLERANCE = 1.0

SEP = "=" * 100


def section(t):
    print(f"\n{SEP}\n  {t}\n{SEP}")


def money(v):
    return f"{(v or 0.0):,.0f}".replace(",", ".")


Picking = env['stock.picking'].sudo()


section("1. LỖI 'CHỜ HĐ HOÀI' — cron tự quét bù, chỉ đếm để theo dõi")
requested = Picking.search_count([('misa_invoice_state', '=', 'requested')])
missing = Picking.search_count([('misa_invoice_state', '=', 'missing')])
print(f"  Đang 'Đã đề nghị, chờ HĐ' : {requested} phiếu")
print(f"  Đang 'Chưa có đề nghị'    : {missing} phiếu")
print("  -> Cả 2 nhóm đều nằm trong domain cron (_misa_invoice_scan_domain loại phiếu 'invoiced'),")
print("     nên sau khi deploy bản sửa, cron tự kiểm tra lại. Chạy lại script này sau vài giờ,")
print("     con số 'chờ HĐ' phải giảm dần.")


section("2. LỖI 'GÁN ĂN THEO DÙ CHỈ PHỦ 1 PHẦN' — cron bỏ qua, phải quét bù tay")

# Lọc thô trong DB trước (rẻ), rồi mới so tiền trong Python — điều kiện so 2 field với nhau
# không diễn đạt được bằng domain Odoo.
candidates = Picking.search([
    ('misa_invoice_master_picking_id', '!=', False),
    ('misa_invoice_grouped_matched_amount', '>', 0.01),
])
print(f"  Phiếu có master_picking VÀ có khớp dòng hàng: {len(candidates)}")

wrong = Picking.browse()
for picking in candidates:
    matched = picking.misa_invoice_grouped_matched_amount or 0.0
    net = picking.misa_invoice_net_actual_amount or 0.0
    if net > 0 and matched < net - TOLERANCE:
        wrong |= picking

if not wrong:
    print("  ✅ Không có phiếu nào bị gán ăn theo sai. Không cần quét bù.")
else:
    hidden_total = sum(
        (p.misa_invoice_net_actual_amount or 0.0) - (p.misa_invoice_grouped_matched_amount or 0.0)
        for p in wrong
    )
    print(f"  ⚠️ {len(wrong)} phiếu bị gán ăn theo SAI — tổng tiền đang bị giấu:"
          f" {money(hidden_total)} đ\n")
    print(f"  {'PHIẾU':<20}{'ĐƠN HÀNG':<24}{'THỰC XUẤT':>14}{'ĐÃ PHỦ':>14}{'CÒN THIẾU':>14}  ĂN THEO")
    for p in wrong:
        matched = p.misa_invoice_grouped_matched_amount or 0.0
        net = p.misa_invoice_net_actual_amount or 0.0
        orders = ', '.join(p.misa_invoice_sale_order_ids.mapped('name')) or '—'
        print(f"  {p.name:<20}{orders[:22]:<24}{money(net):>14}{money(matched):>14}"
              f"{money(net - matched):>14}  {p.misa_invoice_master_picking_id.name}")

    section("3. QUÉT BÙ")
    if not APPLY:
        print("  APPLY = False -> chưa sửa gì. Đổi APPLY = True ở đầu file rồi chạy lại để quét bù.")
        print(f"  Khi chạy thật sẽ xử lý tối đa {MAX_APPLY} phiếu, mỗi lô {BATCH_SIZE} phiếu.")
    else:
        todo = wrong[:MAX_APPLY]
        print(f"  Quét bù {len(todo)}/{len(wrong)} phiếu (gọi lại action_check_misa_invoice_status)...")
        done = 0
        for index in range(0, len(todo), BATCH_SIZE):
            batch = todo[index:index + BATCH_SIZE]
            try:
                batch.action_check_misa_invoice_status()
                done += len(batch)
                print(f"    ... {done}/{len(todo)} phiếu")
            except Exception as e:
                print(f"    ❌ Lô bắt đầu từ {batch[0].name}: {type(e).__name__}: {e}")

        # Đọc lại để xác nhận đã lành — hàm dedupe đã sửa sẽ GỠ master của phiếu phủ 1 phần.
        # Phải invalidate: dedupe ghi qua 1 recordset KHÁC (nó tự search lại theo request_refid),
        # đọc thẳng từ cache của `todo` có thể ra giá trị cũ trước khi gỡ.
        todo.invalidate_recordset(['misa_invoice_master_picking_id'])
        still_wrong = todo.filtered(lambda p: p.misa_invoice_master_picking_id)
        print(f"\n  Sau quét bù: còn {len(still_wrong)} phiếu vẫn giữ master_picking.")
        if still_wrong:
            print(f"    {still_wrong.mapped('name')}")
            print("    (kiểm tra tay: có thể MISA đã xuất thêm hóa đơn nên giờ phủ đủ thật)")

print(f"\n{SEP}\n  XONG{' — chỉ đọc, không sửa gì.' if not APPLY else ''}\n{SEP}")
