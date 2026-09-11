# -*- coding: utf-8 -*-
"""
check_loyalty_zero_points_tmbc090226.py
========================================
Tra vì sao phiếu KBC/OUT/12646 (SO: TMBC090226) log ra
"Tích ranking=0 exchange=0 ... qua 2 tài khoản" - tức là CẢ 2 loại điểm
đều tính ra 0 cho CẢ 2 tài khoản phân bổ, không tạo được bản ghi nào.

CHỈ ĐỌC — không write/create/unlink gì.

Chạy bằng lệnh (trên Odoo.sh shell):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_loyalty_zero_points_tmbc090226.py

Sửa SALE_ORDER_NAME / PICKING_NAME bên dưới nếu muốn dò đơn khác.
"""

SALE_ORDER_NAME = 'TMBC090226'
PICKING_NAME = 'KBC/OUT/12646'

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
        print(
            f"    account=#{aline.account_id.id} {aline.account_id.display_name!r} "
            f"active={aline.account_id.active!r} earning_pct={aline.earning_pct!r}"
        )

    print("\n  --- Toàn bộ portal account của root_partner (kể cả không được chọn trên đơn) ---")
    for acc in root.loyalty_portal_account_ids:
        print(f"    #{acc.id} {acc.display_name!r} active={acc.active!r} is_default={acc.is_default!r}")

    has_active_portal = env['hlv.loyalty.portal.account'].sudo().search_count([
        ('partner_id', '=', root.id), ('active', '=', True),
    ])
    print(f"\n  has_active_portal_account (điều kiện chặn đầu hàm _loyalty_earn_points) = {has_active_portal}")


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
    print(f"  move_ids: {len(picking.move_ids)} move(s), done: {len(picking.move_ids.filtered(lambda m: m.state == 'done'))}")

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

        ranking_points = 0
        if program and delivered_subtotal > 0 and program.earning_amount > 0:
            ranking_points = int(delivered_subtotal / program.earning_amount) * program.earning_points
        print(f"  ranking_points (cả đơn, tính lại) = {ranking_points}")
        if delivered_subtotal <= 0:
            print("    => 0 vì delivered_subtotal <= 0 (không có move nào state=done gắn sale_line, hoặc giá/qty = 0)")
        elif program and delivered_subtotal < program.earning_amount:
            print(f"    => 0 vì delivered_subtotal ({delivered_subtotal:,.0f}) < earning_amount ({program.earning_amount:,.0f}) - CHƯA ĐỦ MỐC tích 1 điểm")

        discount_amount, discount_details, discount_formula_source = (
            picking._compute_loyalty_discount_amount(delivered_lines, delivered_subtotal, so.partner_id)
        )
        print(f"\n  discount_formula_source = {discount_formula_source!r}")
        print(f"  discount_amount (tính lại) = {discount_amount:,.2f}")
        for d in discount_details:
            print(
                f"    - product={d['product']!r} qty={d['qty']} subtotal={d['subtotal']:,.0f} "
                f"source={d['source']!r} rate={d['discount_rate']!r} discount_amount={d['discount_amount']:,.2f}"
            )
        if discount_amount <= 0:
            print("    => 0 vì không có CK Loyalty (%)/tiền trên dòng SO, VÀ root.loyalty_default_discount cũng = 0")

        exchange_points = 0
        if discount_amount > 0 and program and program.discount_per_point > 0:
            exchange_points = int(discount_amount / program.discount_per_point)
        print(f"  => exchange_points (cả đơn, tính lại) = {exchange_points}")

        section("4b. Chia điểm theo từng tài khoản (_split_loyalty_points_by_account)")
        allocations = picking._get_loyalty_account_allocations(so, root)
        print(f"  allocations = {[(a.display_name, pct) for a, pct in allocations]}")
        if allocations and program:
            shares = picking._split_loyalty_points_by_account(
                allocations, delivered_subtotal, discount_amount, program, ranking_points,
                discount_formula_source, discount_details,
            )
            for s in shares:
                print(
                    f"    account={s['account'].display_name!r} "
                    f"ranking_points={s['ranking_points']} exchange_points={s['exchange_points']}"
                )
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

section("6. Kết luận gợi ý")
print(
    "  - Nếu mục 4 cho ranking_points=0 VÀ exchange_points=0: log '0/0' là ĐÚNG, không phải bug -\n"
    "    phiếu này thực sự chưa đủ điều kiện tích điểm nào (xem lý do in kèm ở mục 4: doanh số\n"
    "    giao chưa đủ mốc earning_amount, và/hoặc không có CK Loyalty % + default_discount=0).\n"
    "  - Nếu mục 4 cho ranking_points>0 hoặc exchange_points>0 nhưng mục 4b cho tất cả account đều\n"
    "    0 điểm: do allocations/pct trên bảng phân bổ tài khoản có vấn đề (VD tổng % quá nhỏ, hoặc\n"
    "    round() làm tròn về 0) - xem chi tiết allocations + shares ở mục 4b.\n"
    "  - Nếu mục 4b cho account có điểm >0 nhưng mục 5 không thấy bản ghi nào: cần check lại xem\n"
    "    module hlv_loyalty đã được upgrade với code fix mới nhất chưa (-u hlv_loyalty)."
)
