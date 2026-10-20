# -*- coding: utf-8 -*-
"""
fix_misa_invoice_unallocated_invoiced.py
========================================
Sửa phiếu báo "Đã xuất HĐ" mà số theo đơn KHÔNG quy đồng HĐ nào về phiếu (HĐ chia 0 đ).

Case 20/10/2026: phiếu giao đợt sau, tra theo tên không ra đề nghị → tìm theo mã đơn nhận nhầm
đề nghị của đợt / đơn khác → bị gộp dự phòng theo refid → báo "Đã xuất HĐ":
  KBC/OUT/14107 (DH…237496) nhận DN125524949235071 — HĐ của đợt 13905
  KBC/OUT/14255 (DH…237496) nhận KBC/OUT/14084    — toàn dòng của DH…237743
  KBC/OUT/14113 (DH…235907) nhận DN125524949235008 — hàng đã giao ở 12663
Module đã sửa đường tìm theo mã đơn (bỏ đề nghị của phiếu khác cùng đơn, đòi đề nghị có dòng
đúng đơn + đúng mã hàng phiếu đã xuất). File này đưa các phiếu đó về "Chưa kiểm tra" rồi kiểm tra
lại MISA bằng luật mới — phiếu có đề nghị thật sẽ về đúng, phiếu chưa có sẽ về "Chưa có đề nghị".

Logic nằm trong module (stock.picking.misa_invoice_unallocated_invoiced_ids /
recheck_misa_invoice_from_scratch), file này chỉ gọi và in.

DRY_RUN = True: chỉ liệt kê, không ghi, không gọi MISA.
DRY_RUN = False: từng phiếu kiểm lại + commit; phiếu lỗi bỏ qua, in cuối, chạy lại là thử lại.

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    cd ~/src/user
    odoo-bin shell -d <TEN_DATABASE> < bin/fix_misa_invoice_unallocated_invoiced.py
"""

DRY_RUN = True
ONLY_PICKINGS = []          # để trống = mọi phiếu tìm được; hoặc ['KBC/OUT/14107', ...] để thử vài phiếu
SEP = "=" * 100

Picking = env['stock.picking'].sudo()
if not hasattr(Picking, 'misa_invoice_unallocated_invoiced_ids'):
    raise SystemExit("❌ Server chưa có bản mới của models/misa_invoice_grouped_repair.py — deploy trước.")


def money(v):
    return f"{(v or 0.0):,.0f}".replace(",", ".")


pickings = Picking.browse(Picking.misa_invoice_unallocated_invoiced_ids())
if ONLY_PICKINGS:
    pickings = pickings.filtered(lambda p: p.name in ONLY_PICKINGS)
print(f"\n{SEP}\n  {'CHẠY THỬ' if DRY_RUN else 'SỬA THẬT'} — {len(pickings)} phiếu báo 'Đã xuất HĐ' mà HĐ chia 0 đ\n{SEP}")
for p in pickings.sorted('date_done'):
    print(f"    {p.name:<16} {p.date_done:%d/%m/%Y} {', '.join(p.misa_invoice_sale_order_ids.mapped('name')):<20}"
          f" thực xuất {money(p.misa_invoice_net_actual_amount):>12} | đề nghị {p.misa_invoice_request_refno or '—'}"
          f" | HĐ {p.misa_invoice_no or '—'} | ăn theo {p.misa_invoice_master_picking_id.name or '—'}")

if DRY_RUN:
    print("\n  Chạy thử — không ghi gì. Đặt DRY_RUN = False để kiểm lại thật (gọi MISA, mỗi phiếu ~2–4 lệnh).")
else:
    failed = []
    print("\n  KẾT QUẢ (trước → sau):")
    for picking_id in pickings.ids:
        try:
            row = Picking.recheck_misa_invoice_from_scratch(picking_id)
        except Exception as exc:
            env.cr.rollback()
            env.invalidate_all()
            failed.append(f"{Picking.browse(picking_id).name}: {exc}")
            continue
        env.cr.commit()
        print(f"    {row['name']:<16} {row['before']}  →  {row['after']}")
    if failed:
        print(f"\n  ⚠️ {len(failed)} phiếu lỗi, chạy lại để thử lại:\n    " + "\n    ".join(failed))
    print("\n  ✅ Đã commit từng phiếu.")
print(SEP)
