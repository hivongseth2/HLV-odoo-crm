# -*- coding: utf-8 -*-
"""
check_loyalty_missing_exchange_ckbc060226test.py
=================================================
Tra vì sao đơn CKBC060226TEST (phiếu KBC/OUT/12645) chỉ tạo được
"Tích điểm xếp hạng" (28 điểm) mà KHÔNG tạo "Tích điểm đổi thưởng".

CHỈ ĐỌC — không write/create/unlink gì (chỉ gọi hàm private để lấy số liệu
tính toán lại trong bộ nhớ, không lưu DB).

Chạy bằng lệnh (trên Odoo.sh shell):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_loyalty_missing_exchange_ckbc060226test.py

Sửa SALE_ORDER_NAME / PICKING_NAME bên dưới nếu muốn dò đơn khác.
"""

SALE_ORDER_NAME = 'CKBC060226TEST'
PICKING_NAME = 'KBC/OUT/12645'

SEP = "=" * 90
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")


section("1. Đơn bán hàng")
so = env['sale.order'].sudo().search([('name', '=', SALE_ORDER_NAME)], limit=1)
if not so:
    print(f"  KHÔNG tìm thấy sale.order name={SALE_ORDER_NAME!r}")
else:
    print(f"  SO #{so.id} {so.name!r} state={so.state!r} company={so.company_id.name!r}")
    print(f"  partner_id: #{so.partner_id.id} {so.partner_id.display_name!r}")
    root = so.partner_id._get_loyalty_root()
    print(f"  root_partner (_get_loyalty_root): #{root.id} {root.display_name!r}")
    print(f"  root.loyalty_default_discount = {root.loyalty_default_discount!r}")

    print("\n  --- Dòng bán hàng (order_line) ---")
    for line in so.order_line:
        print(
            f"    line #{line.id} product={line.product_id.display_name!r} "
            f"price_unit={line.price_unit} qty={line.product_uom_qty} "
            f"loyalty_discount_pct={getattr(line, 'loyalty_discount_pct', None)!r} "
            f"x_studio_loyalty_discount_amount={getattr(line, 'x_studio_loyalty_discount_amount', 'FIELD_NOT_FOUND')!r}"
        )

    print("\n  --- Tài khoản cộng điểm cấu hình trên đơn (loyalty_account_line_ids) ---")
    if not so.loyalty_account_line_ids:
        print("    (trống -> fallback tài khoản mặc định của công ty)")
    for aline in so.loyalty_account_line_ids:
        print(f"    account={aline.account_id.display_name!r} earning_pct={aline.earning_pct!r}")


section("2. Phiếu xuất kho")
picking = env['stock.picking'].sudo().search([('name', '=', PICKING_NAME)], limit=1)
if not picking:
    print(f"  KHÔNG tìm thấy stock.picking name={PICKING_NAME!r}")
else:
    print(
        f"  Picking #{picking.id} {picking.name!r} state={picking.state!r} "
        f"picking_type_code={picking.picking_type_code!r} sale_id={picking.sale_id.name!r} "
        f"date_done={picking.date_done!r} loyalty_points_earned={picking.loyalty_points_earned!r}"
    )

    section("3. Chương trình Loyalty đang active")
    program = env['hlv.loyalty.program'].sudo().search([('active', '=', True)], limit=1)
    if not program:
        print("  KHÔNG có chương trình loyalty nào active!")
    else:
        print(
            f"  Program #{program.id} company={program.company_id.name!r} "
            f"earning_amount={program.earning_amount} earning_points={program.earning_points} "
            f"discount_per_point={program.discount_per_point}"
        )

    section("4. Tính lại delivered_lines / discount_amount / ranking / exchange (KHÔNG lưu DB)")
    try:
        delivered_lines = picking._get_loyalty_delivered_lines()
        delivered_subtotal = sum((l['price_unit'] or 0.0) * (l['qty'] or 0.0) for l in delivered_lines)
        print(f"  delivered_subtotal = {delivered_subtotal:,.0f}")
        for l in delivered_lines:
            sl = l['sale_line']
            print(
                f"    - product={l['product'].display_name!r} qty={l['qty']} "
                f"price_unit={l['price_unit']} sale_line={'#%d' % sl.id if sl else None}"
            )

        if program:
            ranking_points = 0
            if delivered_subtotal > 0 and program.earning_amount > 0:
                ranking_points = int(delivered_subtotal / program.earning_amount) * program.earning_points
            print(f"  ranking_points (tính lại) = {ranking_points}")

            discount_amount, discount_details, discount_formula_source = (
                picking._compute_loyalty_discount_amount(delivered_lines, delivered_subtotal, so.partner_id)
            )
            print(f"  discount_formula_source = {discount_formula_source!r}")
            print(f"  discount_amount (tính lại) = {discount_amount:,.2f}")
            for d in discount_details:
                print(
                    f"    - product={d['product']!r} qty={d['qty']} subtotal={d['subtotal']:,.0f} "
                    f"source={d['source']!r} rate={d['discount_rate']!r} discount_amount={d['discount_amount']:,.2f}"
                )

            exchange_points = 0
            if discount_amount > 0 and program.discount_per_point > 0:
                exchange_points = int(discount_amount / program.discount_per_point)
            print(f"  => exchange_points (tính lại theo dữ liệu HIỆN TẠI) = {exchange_points}")
    except Exception as e:
        print(f"  Lỗi khi tính lại: {e!r}")

    section("5. Bản ghi Lịch sử điểm (hlv.loyalty.history) đã có cho phiếu này")
    hist = env['hlv.loyalty.history'].sudo().search([('picking_id', '=', picking.id)], order='id')
    if not hist:
        print("  (không có bản ghi nào)")
    for h in hist:
        print(
            f"  #{h.id} account={h.account_id.display_name!r} point_type={h.point_type!r} "
            f"state={h.state!r} point_amount={h.point_amount} transaction_type={h.transaction_type!r} "
            f"create_date={h.create_date}"
        )
        if h.point_formula:
            print(f"      formula: {h.point_formula[:300]}")

section("6. Kết luận gợi ý")
print(
    "  - Nếu mục 4 cho exchange_points > 0 NHƯNG mục 5 không có bản ghi point_type=exchange nào:\n"
    "    => đúng bug đã biết: phiếu đã có bản ghi 'earn' (ranking) từ lần validate trước (lúc đó\n"
    "       discount_amount=0), nên code cũ bỏ qua vĩnh viễn, không tạo bù exchange khi dữ liệu\n"
    "       CK Loyalty được nhập/sửa sau. Đã sửa trong models/stock_picking.py (nhánh 'existing')\n"
    "       để tự bù bản ghi còn thiếu, và thêm nút 'Tạo bù điểm Loyalty' trên đơn bán hàng.\n"
    "  - Nếu mục 4 cho exchange_points = 0: do discount_amount=0 (dòng SO chưa có\n"
    "    loyalty_discount_pct / x_studio_loyalty_discount_amount, VÀ root.loyalty_default_discount=0)\n"
    "    -> cần nhập CK Loyalty (%) trên dòng bán hàng rồi bấm nút 'Tạo bù điểm Loyalty'."
)
