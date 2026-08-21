# -*- coding: utf-8 -*-
"""
verify_packing_status_fix.py
=================================
Xác nhận fix packing_status trong delivery_planner_stock.py: thêm accumulator
total_avail_active_move (chỉ tính hàng của dòng CÒN move active — chưa done/cancel), dùng
riêng cho quyết định packing_status thay cho total_avail (vốn còn cộng cả hàng của dòng ĐÃ
lấy+đóng gói xong, nằm ở vị trí đầu ra nội bộ, chỉ đang chờ qty_delivered cập nhật ở OUT cuối).

Đơn DH125524949234879: dòng PF113A-E đã đóng gói xong (đi theo PICK/10836 -> PACK/07777, move
đã done), dòng T48A-3C-A-HANYOUNG thực sự hết hàng (còn move active, không có tồn). Trước fix,
total_avail > 0 (nhờ PF113A-E) làm packing_status rơi vào nhánh 'unpacked' dù T48A-3C-A-HANYOUNG
không có gì để đóng gói. Sau fix, kỳ vọng packing_status = 'waiting_stock'.

CHỈ ĐỌC — không write/create/unlink gì.

Chạy bằng lệnh (trên Odoo.sh shell):
    python odoo-bin shell -d <TEN_DATABASE> < bin/verify_packing_status_fix.py
"""

ORDER_NAME = "DH125524949235568"  # đổi nếu cần

SEP = "=" * 100
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

so = env['sale.order'].sudo().search([('name', '=', ORDER_NAME)], limit=1)
if not so:
    print(f"  Không tìm thấy đơn {ORDER_NAME!r}")
else:
    section(f"Đơn {so.name} (id={so.id}, state={so.state})")

    print("  -- Từng dòng bán hàng (sale.order.line) --")
    for sol in so.order_line:
        if not sol.product_id or sol.product_id.type == 'service':
            continue
        print(
            f"  line #{sol.id:>6} {sol.product_id.display_name[:35]:35s} "
            f"qty_ord={sol.product_uom_qty:>7.2f} qty_del={sol.qty_delivered:>7.2f}"
        )

    print("\n  -- Phiếu (stock.picking) --")
    for p in so.picking_ids.sorted('id'):
        print(
            f"  {p.name:20s} seq_code={p.picking_type_id.sequence_code or '':6s} "
            f"state={p.state:10s} x_printed={getattr(p, 'x_printed', '?')!s:6s}"
        )

    section("Giá trị TÍNH LIVE ngay bây giờ (sau fix)")
    Service = env['hlv.delivery.planner.service'].sudo()
    _s, _mids, _stats, _avail, _onhand, status_by_so = Service._calculate_po_and_stock_status(
        so, po_date_from='', po_date_to='', po_status='all',
        filter_delivery_status='all', filter_stock_status='all', filter_packing_status='all',
        show_completed=True, filter_need_transfer=False, filter_new_orders=False,
    )
    live = status_by_so.get(so.id, {})
    print(f"  stock_status={live.get('stock_status')!r}  packing_status={live.get('packing_status')!r}")
    print(f"\n  Toàn bộ dict: {live}")

    section("KỲ VỌNG")
    print("  packing_status nên là 'waiting_stock' (không phải 'unpacked') vì dòng còn thiếu hàng")
    print("  (T48A-3C-A-HANYOUNG) thực sự không có tồn/move active nào có thể đóng góp.")
    print("  stock_status giữ nguyên như trước fix (không đổi logic này) — chỉ đổi packing_status.")
