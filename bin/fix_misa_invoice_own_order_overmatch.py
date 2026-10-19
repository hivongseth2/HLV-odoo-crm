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

DRY_RUN = True: tính trong savepoint rồi rollback — không ghi gì, không gọi MISA.

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/fix_misa_invoice_own_order_overmatch.py
"""

DRY_RUN = True
SEP = "=" * 100

Picking = env['stock.picking'].sudo()
if not hasattr(Picking, 'repair_misa_invoice_own_order_overmatch'):
    raise SystemExit("❌ Server chưa có models/misa_invoice_grouped_repair.py — deploy trước.")

report = Picking.repair_misa_invoice_own_order_overmatch(dry_run=DRY_RUN)
print(f"\n{SEP}\n  {'CHẠY THỬ' if DRY_RUN else 'ĐÃ SỬA'} — {len(report)} lượt khớp đổi SL\n{SEP}")
for row in report:
    print(f"    {row['picking']:<16} [{row['item']}] khớp từ đề nghị {row['master']}: {row['before']:g} → {row['after']:g}"
          f"{'  → GỠ ăn theo' if row['released'] else ''}")

released = sorted({row['picking'] for row in report if row['released']})
print(f"\n  {len(released)} phiếu gỡ ăn theo: {', '.join(released) or '—'}")
if not DRY_RUN:
    for picking in Picking.search([('name', 'in', released)]):
        print(f"    {picking.name}: {picking.misa_invoice_state} | đề nghị {picking.misa_invoice_request_refno or '—'}"
              f" | HĐ {picking.misa_invoice_no or '—'}")
    env.cr.commit()
    print("  ✅ Đã commit.")
else:
    print("  Chạy thử — đặt DRY_RUN = False để sửa thật.")
print(SEP)
