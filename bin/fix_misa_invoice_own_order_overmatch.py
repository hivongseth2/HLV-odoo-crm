# -*- coding: utf-8 -*-
"""
fix_misa_invoice_own_order_overmatch.py
=======================================
Sửa phiếu giao ĐỢT SAU bị báo "Đã xuất HĐ" bằng HĐ của đợt trước cùng đơn (case
DH125524949235092: KBC/OUT/14143 giao thêm 2 cái, ăn theo đề nghị 8 cái của KBC/OUT/11995).

Khớp lại mọi dòng xuất HĐ chung thuộc CHÍNH đơn của phiếu đại diện theo luật mới (SL phiếu đại
diện đã xuất được trừ trước, chỉ phần dư mới chia cho phiếu khác). Phiếu ăn theo không còn được
phủ đủ thì gỡ ăn theo, trả về "Chưa kiểm tra" rồi kiểm tra lại MISA — phiếu có đề nghị riêng
(như 14143 giờ đã có đề nghị KBC/OUT/14143) sẽ về đúng trạng thái của đề nghị đó.

Logic nằm trong module (stock.picking.repair_misa_invoice_own_order_overmatch), file này chỉ gọi
và in kết quả. Cần deploy module có models/misa_invoice_grouped_repair.py trước.

Chạy TỪNG phiếu đại diện, mỗi phiếu 1 savepoint ngắn: chạy 1 lèo trong 1 giao dịch thì giữ khóa
cả mấy phút, đụng cron kiểm tra MISA là deadlock. Phiếu nào lỗi (deadlock...) thì bỏ qua, in ra
cuối — chạy lại script là thử lại phiếu đó.

DRY_RUN = True: mỗi phiếu tính trong savepoint rồi rollback — không ghi gì, không gọi MISA.
Log "deleted misa.invoice.grouped.match" vẫn hiện (Odoo log lúc chạy lệnh xóa) nhưng bị
rollback ngay sau đó.

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    cd ~/src/user
    odoo-bin shell -d <TEN_DATABASE> < bin/fix_misa_invoice_own_order_overmatch.py
"""

DRY_RUN = True
SEP = "=" * 100

Picking = env['stock.picking'].sudo()
if not hasattr(Picking, 'misa_invoice_own_order_overmatch_master_ids'):
    raise SystemExit("❌ Server chưa có bản mới của models/misa_invoice_grouped_repair.py — deploy trước.")

master_ids = Picking.misa_invoice_own_order_overmatch_master_ids()
print(f"\n{SEP}\n  {'CHẠY THỬ' if DRY_RUN else 'SỬA THẬT'} — {len(master_ids)} phiếu đại diện cần khớp lại\n{SEP}")

report, failed = [], []
for index, master_id in enumerate(master_ids, 1):
    name = Picking.browse(master_id).name
    try:
        rows = Picking.repair_misa_invoice_own_order_overmatch(master_id, dry_run=DRY_RUN)
    except Exception as exc:
        env.cr.rollback()
        env.invalidate_all()
        failed.append(f"{name}: {exc.__class__.__name__}")
        continue
    if not DRY_RUN:
        env.cr.commit()
    for row in rows:
        print(f"    {row['picking']:<16} [{row['item']}] khớp từ đề nghị {row['master']}: {row['before']:g} → {row['after']:g}"
              f"{'  → GỠ ăn theo' if row['released'] else ''}")
    report += rows
    if index % 20 == 0:
        print(f"  … {index}/{len(master_ids)}")

released = sorted({row['picking'] for row in report if row['released']})
print(f"\n  {len(report)} lượt khớp đổi SL | {len(released)} phiếu gỡ ăn theo: {', '.join(released) or '—'}")
if failed:
    print(f"  ⚠️ {len(failed)} phiếu đại diện lỗi, chạy lại script để thử lại: {'; '.join(failed)}")
if not DRY_RUN:
    for picking in Picking.search([('name', 'in', released)]):
        print(f"    {picking.name}: {picking.misa_invoice_state} | đề nghị {picking.misa_invoice_request_refno or '—'}"
              f" | HĐ {picking.misa_invoice_no or '—'}")
    print("  ✅ Đã commit từng phiếu.")
else:
    print("  Chạy thử — không ghi gì. Đặt DRY_RUN = False để sửa thật.")
print(SEP)
