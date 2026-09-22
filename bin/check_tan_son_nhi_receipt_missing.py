# -*- coding: utf-8 -*-
"""
check_tan_son_nhi_receipt_missing.py
=====================================
Trang "Tổng quan Kho" của Kho Tân Sơn Nhì chỉ hiện 6 thẻ: Lệnh chuyển hàng nội bộ,
Lấy hàng, Gói, Lệnh giao hàng, Sản xuất, Đơn hàng POS — KHÔNG có thẻ "Nhận hàng"
(phiếu nhập kho / receipts) như một kho bình thường luôn phải có.

Script này kiểm tra vì sao thẻ "Nhận hàng" biến mất, theo thứ tự khả nghi:
  1. Warehouse Tân Sơn Nhì có tồn tại, có in_type_id (loại phiếu nhập) không.
  2. Loại phiếu nhập (stock.picking.type code='incoming') của kho này còn active
     không — nếu bị archive thì kanban Tổng quan Kho sẽ không hiện thẻ đó nữa dù
     dữ liệu phiếu cũ vẫn còn nguyên.
  3. Company của warehouse/picking type có khớp company hiện tại của user không
     (đa công ty — lệch company cũng khiến thẻ biến mất khỏi overview).
  4. Có phiếu nhập kho (stock.picking, picking_type code='incoming') nào thuộc
     kho này không, dù type có bị ẩn hay không — để biết dữ liệu "phiếu nhập kho"
     thực tế đang ở đâu, có bị kẹt/nằm chờ hay không.
  5. reception_steps hiện tại của kho (một số cấu hình 1 bước có thể gộp khác đi).

CHỈ ĐỌC — không write/create/unlink gì.

Chạy bằng lệnh (trên Odoo.sh shell, hoặc odoo-bin shell tại môi trường đang chạy):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_tan_son_nhi_receipt_missing.py
"""

WAREHOUSE_NAME_LIKE = "Tân Sơn Nhì"  # đổi nếu tên kho khác đi

SEP = "=" * 100
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

section("1) Warehouse khớp tên")
WH = env['stock.warehouse'].sudo().with_context(active_test=False)
warehouses = WH.search([('name', 'ilike', WAREHOUSE_NAME_LIKE)])
if not warehouses:
    warehouses = WH.search([('code', 'ilike', 'TSN')])
if not warehouses:
    print(f"  KHÔNG tìm thấy warehouse nào khớp {WAREHOUSE_NAME_LIKE!r} hay code TSN.")
for wh in warehouses:
    print(f"  - {wh.name} (id={wh.id}, code={wh.code!r}) active={wh.active} "
          f"company={wh.company_id.name!r} (company_id={wh.company_id.id}) "
          f"reception_steps={wh.reception_steps!r} delivery_steps={wh.delivery_steps!r}")

if not warehouses:
    section("DỪNG — không có warehouse để kiểm tra tiếp")
else:
    wh = warehouses[0]
    print(f"\n  -> Dùng warehouse #{wh.id} ({wh.name}) cho các bước sau.")

    section("2) in_type_id (loại phiếu NHẬN HÀNG) khai báo trên warehouse")
    in_type = wh.in_type_id
    if not in_type:
        print("  Warehouse KHÔNG có in_type_id nào được gán — đây gần như chắc chắn là lý do "
              "thẻ 'Nhận hàng' không xuất hiện. Cần vào Kho hàng > Cấu hình > Kho hàng, kiểm "
              "tra lại cấu hình kho này.")
    else:
        print(f"  in_type_id = {in_type.name!r} (id={in_type.id}) active={in_type.active} "
              f"sequence_code={in_type.sequence_code!r} code={in_type.code!r} "
              f"company_id={in_type.company_id.id} ({in_type.company_id.name!r}) "
              f"sequence={in_type.sequence}")
        print(f"  in_type_id.warehouse_id (field warehouse_id NGAY TRÊN type #9) = "
              f"{in_type.warehouse_id.id!r} ({in_type.warehouse_id.name!r})")
        if not in_type.active:
            print("  -> BỊ ARCHIVE (active=False) — đây là lý do thẻ không hiện trên Tổng quan Kho.")
        elif in_type.warehouse_id.id != wh.id:
            print(f"  -> LỆCH DỮ LIỆU: warehouse.in_type_id trỏ tới type #{in_type.id}, nhưng chính "
                  f"type #{in_type.id} lại có warehouse_id={in_type.warehouse_id.id!r} (khác kho "
                  f"#{wh.id} đang xét). Tổng quan Kho hiển thị thẻ theo warehouse_id NGAY TRÊN "
                  f"picking.type (không đi qua warehouse.in_type_id), nên thẻ 'Nhận hàng' biến mất "
                  f"dù type vẫn active. Cần vào Cài đặt (dev mode) > Kho hàng > Loại hoạt động, mở "
                  f"'{in_type.name}' và gán lại Kho hàng = 'Kho Tân Sơn Nhì'.")

    section("3) TẤT CẢ stock.picking.type (kể cả archived) của warehouse này")
    PT = env['stock.picking.type'].sudo().with_context(active_test=False)
    types = PT.search([('warehouse_id', '=', wh.id)], order='sequence')
    if not types:
        print("  KHÔNG có picking.type nào trỏ warehouse_id = warehouse này.")
    for t in types:
        flag = "" if t.active else "  <-- ĐANG BỊ ẨN (active=False)"
        print(f"  - [{t.code:10s}] {t.name!r} (id={t.id}) active={t.active} "
              f"sequence={t.sequence}{flag}")

    section("4) So company: user hiện tại vs warehouse/in_type")
    print(f"  env.user.company_id      = {env.user.company_id.name!r} (id={env.user.company_id.id})")
    print(f"  env.user.company_ids     = {env.user.company_ids.mapped('name')}")
    print(f"  warehouse.company_id     = {wh.company_id.name!r} (id={wh.company_id.id})")
    if wh.company_id.id not in env.user.company_ids.ids:
        print("  -> User hiện tại KHÔNG thuộc công ty của warehouse này -> mọi thẻ của kho này "
              "(kể cả các thẻ đang thấy) đáng lẽ không hiện — nếu vẫn thấy các thẻ khác thì đây "
              "không phải nguyên nhân, bỏ qua mục này.")

    section("5) Phiếu nhập kho (stock.picking, code='incoming') thực tế thuộc kho này")
    Picking = env['stock.picking'].sudo().with_context(active_test=False)
    incoming_pickings = Picking.search([
        ('picking_type_id.warehouse_id', '=', wh.id),
        ('picking_type_id.code', '=', 'incoming'),
    ])
    if not incoming_pickings:
        print("  KHÔNG có bất kỳ phiếu nhập kho nào (kể cả cũ/hủy) gắn với kho này.")
    else:
        from collections import Counter
        by_state = Counter(incoming_pickings.mapped('state'))
        print(f"  Tổng số phiếu nhập kho: {len(incoming_pickings)}  — theo state: {dict(by_state)}")
        print("\n  -- 10 phiếu gần nhất --")
        for p in incoming_pickings.sorted('id', reverse=True)[:10]:
            print(f"    {p.name} (id={p.id}) state={p.state} active={p.active} "
                  f"scheduled_date={p.scheduled_date} origin={p.origin!r}")

    if in_type:
        section("5b) Phiếu tìm THẲNG theo picking_type_id = in_type_id (bỏ qua warehouse_id, "
                "phòng trường hợp warehouse_id trên type bị lệch như mục 2)")
        direct_pickings = Picking.search([('picking_type_id', '=', in_type.id)])
        if not direct_pickings:
            print(f"  KHÔNG có phiếu nào dùng picking_type_id={in_type.id} — kho này CHƯA TỪNG "
                  f"phát sinh phiếu nhập kho nào qua type '{in_type.name}'.")
        else:
            from collections import Counter as _Counter
            by_state2 = _Counter(direct_pickings.mapped('state'))
            print(f"  Tổng số: {len(direct_pickings)} — theo state: {dict(by_state2)}")
            print("\n  -- 10 phiếu gần nhất --")
            for p in direct_pickings.sorted('id', reverse=True)[:10]:
                print(f"    {p.name} (id={p.id}) state={p.state} active={p.active} "
                      f"scheduled_date={p.scheduled_date} origin={p.origin!r}")

section("KẾT LUẬN GỢI Ý")
print("  - Nếu in_type_id rỗng hoặc active=False (mục 2) -> đó là lý do thẻ 'Nhận hàng' biến mất")
print("    khỏi Tổng quan Kho; kích hoạt (Unarchive) lại picking type đó trong Cấu hình > Loại")
print("    hoạt động (Operations Types), hoặc gán lại in_type_id đúng cho warehouse.")
print("  - Nếu company lệch (mục 4) -> đổi công ty đang làm việc (company switcher) rồi xem lại.")
print("  - Nếu mục 5 vẫn ra phiếu nhập kho bình thường (state khác nhau) -> dữ liệu phiếu KHÔNG")
print("    mất, chỉ có THẺ trên overview bị ẩn do picking type bị archive/cấu hình sai — không")
print("    cần lo dữ liệu, chỉ cần sửa lại hiển thị.")
