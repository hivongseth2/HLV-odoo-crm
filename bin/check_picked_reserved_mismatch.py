# -*- coding: utf-8 -*-
"""
check_picked_reserved_mismatch.py
====================================
Đơn DH125524949234923: user hủy dự trữ (unreserve) rồi dự trữ lại (reserve) cho phiếu lấy
hàng — sau đó validate phiếu bị lỗi "You cannot validate a transfer if no quantities are
reserved, or if only non-reserved moves are picked." — đúng dấu hiệu bug cột "Đã lấy hàng"
(move_line.picked) bị giữ nguyên =True từ TRƯỚC lúc unreserve, nhưng quantity đã bị reset về 0
lúc reserve lại — Odoo validate thấy "picked nhưng quantity=0" nên chặn.

Script này in ra state/picked/quantity/reserved của từng move + move_line cho các phiếu của
đơn, để xác nhận đúng mismatch trước khi quyết định cách sửa (đổi picked=False cho move_line
có quantity=0, hoặc xóa move_line rác).

CHỈ ĐỌC — không write/create/unlink gì.

Chạy bằng lệnh (trên Odoo.sh shell):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_picked_reserved_mismatch.py
"""

ORDER_NAME = "DH125524949234923"  # đổi nếu cần

SEP = "=" * 100
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

so = env['sale.order'].sudo().search([('name', '=', ORDER_NAME)], limit=1)
if not so:
    print(f"  Không tìm thấy đơn {ORDER_NAME!r}")
else:
    section(f"Đơn {so.name} (id={so.id}, state={so.state})")
    pickings = so.picking_ids
    print(f"  Tổng số phiếu: {len(pickings)}")

    for p in pickings:
        section(f"Phiếu {p.name} (id={p.id}) — state={p.state} — {p.picking_type_id.name}")

        section2_hdr = (
            f"  {'move_id':>8} {'product':30s} {'state':10s} {'demand':>8} "
            f"{'quantity':>9} {'picked':>7}"
        )
        print(section2_hdr)
        for mv in p.move_ids.sorted('id'):
            print(
                f"  {mv.id:>8} {mv.product_id.display_name[:30]:30s} {mv.state:10s} "
                f"{mv.product_uom_qty:>8.2f} {mv.quantity:>9.2f} {str(mv.picked):>7}"
            )

        print("\n  -- move_line (stock.move.line) chi tiết --")
        line_hdr = (
            f"  {'ml_id':>8} {'move_id':>8} {'product':30s} {'quantity':>9} "
            f"{'picked':>7} {'move.state':>11}"
        )
        print(line_hdr)
        mismatches = []
        for ml in p.move_line_ids.sorted('id'):
            mv_state = ml.move_id.state if ml.move_id else '?'
            print(
                f"  {ml.id:>8} {ml.move_id.id if ml.move_id else 0:>8} "
                f"{(ml.product_id.display_name or '')[:30]:30s} {ml.quantity:>9.2f} "
                f"{str(ml.picked):>7} {mv_state:>11}"
            )
            if ml.picked and (ml.quantity or 0.0) <= 0:
                mismatches.append(ml)

        if mismatches:
            print(f"\n  !!! MISMATCH: {len(mismatches)} move_line có picked=True nhưng quantity=0:")
            for ml in mismatches:
                print(f"      move_line #{ml.id} (move #{ml.move_id.id if ml.move_id else '?'}, "
                      f"product={ml.product_id.display_name})")
        else:
            print("\n  Không thấy move_line nào picked=True mà quantity=0 trên phiếu này.")

section("XONG")
print("  Nếu thấy MISMATCH ở phiếu đang bị lỗi validate -> xác nhận đúng nguyên nhân: cần set")
print("  picked=False cho các move_line đó (hoặc unlink nếu rác hoàn toàn) rồi mới validate lại.")
