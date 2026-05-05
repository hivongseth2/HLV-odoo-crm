# -*- coding: utf-8 -*-
"""
Script chẩn đoán SAVoucher / in_outward detail.
Chạy bằng Odoo shell:
    python odoo-bin shell -d <DB_NAME> < debug_picking_misa.py
Hoặc paste trực tiếp vào Odoo shell.
"""

PICKING_NAME = 'TSN/OUT/08842'   # <-- đổi tên picking cần debug
RESET_FOR_REPUSH = True          # True = xóa refid cũ để push lại fresh

picking = env['stock.picking'].sudo().search([('name', '=', PICKING_NAME)], limit=1)
if not picking:
    print("❌ Không tìm thấy picking:", PICKING_NAME)
else:
    print("=" * 60)
    print(f"Picking     : {picking.name}  (id={picking.id})")
    print(f"State       : {picking.state}")
    print(f"Type code   : {picking.picking_type_code}")
    print(f"Date done   : {picking.date_done}")
    print(f"misa_outward_org_refid : {picking.misa_outward_org_refid!r}")
    print()

    moves = picking.move_ids_without_package
    print(f"Số move lines: {len(moves)}")
    for m in moves:
        print(f"  move id={m.id}  product={m.product_id.name!r}  "
              f"qty_done(quantity)={m.quantity}  "
              f"product_qty={m.product_qty}  "
              f"state={m.state}  "
              f"price_unit={m.price_unit}  "
              f"sale_line_id={m.sale_line_id.id if m.sale_line_id else None}")
        if m.price_unit == 0.0:
            print(f"  ⚠️  price_unit=0 → giá vốn xuất kho sẽ = 0 trên MISA")
            print(f"     standard_price sản phẩm = {m.product_id.standard_price}")

    print()
    filtered_moves = moves.filtered(lambda m: m.quantity > 0)
    print(f"Moves sau filter quantity>0: {len(filtered_moves)}")
    if not filtered_moves:
        print("⚠️  KHÔNG có move nào qua filter → in_outward_detail sẽ TRỐNG!")
        print("   Thử filter theo product_uom_qty > 0:")
        alt = moves.filtered(lambda m: m.product_uom_qty > 0)
        print(f"   Moves với product_uom_qty>0: {len(alt)}")
        for m in alt:
            print(f"     move id={m.id}  product_uom_qty={m.product_uom_qty}  quantity={m.quantity}")

    print()
    so = picking._get_related_sales_order()
    print(f"Sale Order  : {so.name if so else 'KHÔNG TÌM THẤY!'}")
    if so:
        print(f"  SO id     : {so.id}")
        print(f"  misa_sa_voucher_org_refid : {so.misa_sa_voucher_org_refid!r}")
        print(f"  misa_sa_voucher_synced    : {so.misa_sa_voucher_synced}")

    print()
    print("=== Thông tin move_line_ids (stock.move.line - thực tế đã xử lý) ===")
    for ml in picking.move_line_ids:
        print(f"  move_line id={ml.id}  product={ml.product_id.name!r}  "
              f"qty_done={ml.qty_done}  "
              f"lot_name={ml.lot_id.name if ml.lot_id else '-'}")

    # ============================================================
    # RESET để push lại fresh
    # ============================================================
    if RESET_FOR_REPUSH:
        print()
        print("=" * 60)
        print("🔄 RESET để push lại SAVoucher + outward mới...")

        # 1. Xóa outward_refid cũ → lần push tiếp sinh uuid4 mới
        picking.sudo().write({'misa_outward_org_refid': False})
        print(f"  ✅ Đã xóa misa_outward_org_refid trên picking {picking.name}")

        # 2. Reset SAVoucher synced trên SO
        if so:
            so.sudo().write({
                'misa_sa_voucher_synced': False,
                'misa_sa_voucher_org_refid': False,
            })
            # Xóa job sa_voucher cũ nếu còn pending/error
            env['amis.sync.job'].sudo().search([
                ('sale_order_id', '=', so.id),
                ('direction', '=', 'outgoing'),
            ]).unlink()
            print(f"  ✅ Đã reset misa_sa_voucher_synced trên SO {so.name}")

        env.cr.commit()
        print()
        print("✅ Done! Bây giờ vào queue job và tạo lại job outgoing cho picking này,")
        print("   hoặc dùng nút 'Chạy ngay' nếu có job pending.")

