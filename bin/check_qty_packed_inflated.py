# -*- coding: utf-8 -*-
"""
check_qty_packed_inflated.py
=================================
Đơn DH125524949235859: dòng [3VX780-MIS] Dây curoa cao su 3VX780 MITSUSUMI hiện "Chốt Bán"=66
nhưng "Đóng Gói"=264 (đúng 4 lần 66) — nghi ngờ do đơn có NHIỀU dòng sale.order.line trùng
product+price+discount (duplicate lines, thường do MISA sync tạo dòng mới thay vì update dòng
cũ), khiến bước gộp dòng ở FE (groupLines/groupedLines) CỘNG DỒN qty_packed thay vì "giữ 1 giá
trị" — trong khi qty_packed là số liệu THEO SẢN PHẨM cho CẢ ĐƠN (tính 1 lần, lặp lại y hệt trên
MỌI dòng cùng sản phẩm ở backend, xem delivery_planner_formatter.py qty_packed_by_product_id),
không phải số liệu riêng từng dòng như product_uom_qty/qty_delivered.

Script in ra:
  1. TẤT CẢ sale.order.line của đơn khớp sản phẩm 3VX780 — kiểm tra có bao nhiêu dòng trùng
     product+price+discount (sẽ bị FE gộp làm 1 hàng hiển thị).
  2. Số lượng ĐÃ ĐÓNG GÓI THẬT (từ stock.quant.package/move_line, giống logic
     _fetch_packages_for_sales) cho đúng sản phẩm này — để xác nhận con số THẬT là bao nhiêu
     (kỳ vọng 66, không phải 264).
  3. Kết quả gọi lại _format_dashboard_order thật (qua get_dashboard_data) để xem qty_packed
     trả về cho MỖI dòng riêng lẻ trước khi FE gộp — nếu tất cả các dòng trùng đều trả về CÙNG
     1 con số (66) thì xác nhận đúng bug: BE trả đúng, nhưng FE gộp (+=) làm nhân lên N lần.

CHỈ ĐỌC — không write/create/unlink gì.

Chạy bằng lệnh (trên Odoo.sh shell):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_qty_packed_inflated.py
"""

ORDER_NAME = "DH125524949235859"  # đổi nếu cần
PRODUCT_CODE_LIKE = "3VX780"  # đổi nếu cần

SEP = "=" * 100
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

so = env['sale.order'].sudo().search([('name', '=', ORDER_NAME)], limit=1)
if not so:
    print(f"  Không tìm thấy đơn {ORDER_NAME!r}")
else:
    section(f"1) sale.order.line khớp {PRODUCT_CODE_LIKE!r} trong đơn {so.name} (id={so.id})")
    lines = so.order_line.filtered(
        lambda l: l.product_id and PRODUCT_CODE_LIKE in (l.product_id.default_code or '')
    )
    print(f"  Tổng số dòng khớp: {len(lines)}")
    group_key_count = {}
    for l in lines:
        key = (l.product_id.id, l.price_unit, l.discount)
        group_key_count[key] = group_key_count.get(key, 0) + 1
        print(f"    line #{l.id}  product={l.product_id.display_name}  "
              f"qty_ord={l.product_uom_qty}  qty_del={l.qty_delivered}  "
              f"price_unit={l.price_unit}  discount={l.discount}")
    print("\n  -- Nhóm theo (product_id, price_unit, discount) — FE sẽ gộp các dòng CÙNG NHÓM --")
    for key, cnt in group_key_count.items():
        marker = "  <== SẼ BỊ GỘP, qty_packed có thể bị NHÂN LÊN nếu > 1 dòng" if cnt > 1 else ""
        print(f"    product_id={key[0]} price_unit={key[1]} discount={key[2]} -> {cnt} dòng{marker}")

    if not lines:
        print("  Không tìm thấy dòng nào khớp — đổi PRODUCT_CODE_LIKE cho đúng.")
    else:
        product = lines[0].product_id
        section(f"2) Số lượng ĐÃ ĐÓNG GÓI THẬT của sản phẩm {product.display_name} (từ package/move_line)")
        pickings = so.picking_ids
        move_lines = env['stock.move.line'].sudo().search([
            ('picking_id', 'in', pickings.ids),
            ('result_package_id', '!=', False),
            ('product_id', '=', product.id),
            ('state', '!=', 'cancel'),
        ])
        total_real_packed = 0.0
        seen_package_names = {}
        for ml in move_lines:
            pack = ml.result_package_id
            loc = pack.location_id
            is_shipped = not loc or loc.usage not in ('internal', 'transit', 'view')
            print(f"    move_line #{ml.id}  picking={ml.picking_id.name}({ml.picking_id.state})  "
                  f"package={pack.name}  qty={ml.quantity}  location={loc.complete_name if loc else '?'}  "
                  f"is_shipped={is_shipped}")
            if not is_shipped:
                total_real_packed += ml.quantity
                seen_package_names.setdefault(pack.name, 0.0)
                seen_package_names[pack.name] += ml.quantity
        print(f"\n  TỔNG packed THÔ (chưa giao, is_shipped=False, CHƯA áp dụng dedup theo tên kiện/"
              f"picking như code thật _fetch_packages_for_sales) = {total_real_packed}")
        print("  LƯU Ý: nếu 1 kiện xuất hiện ở NHIỀU phiếu kế tiếp nhau (VD PACK done rồi OUT")
        print("  assigned CÙNG package) thì tổng thô này CỘNG DỒN cả 2 phiếu — có thể chính nó")
        print("  mới là chỗ bị đếm trùng, không phải do gộp dòng ở FE. Xem kỹ số ở bước (3) —")
        print("  đó mới là giá trị THẬT SỰ code app tính ra (đã qua dedup nếu có).")
        print("  Theo từng kiện (thô, có thể trùng):")
        for pname, q in seen_package_names.items():
            print(f"    {pname}: {q}")

        section("3) qty_packed trả về từ backend (_format_dashboard_order) cho TỪNG dòng riêng lẻ")
        Service = env['hlv.delivery.planner.service'].sudo()
        result = Service.get_dashboard_data(
            search_query=so.name, filter_warehouse_id='all',
            filter_delivery_status='all', filter_stock_status='all', filter_packing_status='all',
            show_completed=True, filter_new_orders=False,
        )
        matched = [o for o in result.get('orders', []) if o.get('id') == so.id]
        if not matched:
            print("  Không thấy đơn trong kết quả get_dashboard_data (có thể do filter mặc định).")
        else:
            order_data = matched[0]
            for l in order_data.get('lines', []):
                if l.get('product_id') and l['product_id'][0] == product.id:
                    print(f"    line id={l.get('id')}  product_uom_qty={l.get('product_uom_qty')}  "
                          f"qty_packed={l.get('qty_packed')}")

section("KẾT LUẬN")
print("  Nếu ở bước (1) có > 1 dòng CÙNG NHÓM (product+price+discount), và ở bước (3) MỖI dòng")
print("  riêng lẻ đều trả về CÙNG 1 giá trị qty_packed (khớp với tổng packed THẬT ở bước 2, VD")
print("  66) -> xác nhận đúng bug: backend trả ĐÚNG (qty_packed là số liệu chung cho SẢN PHẨM,")
print("  lặp lại trên mọi dòng trùng), nhưng bước GỘP DÒNG ở FE (groupLines/groupedLines) đang")
print("  CỘNG DỒN (+=) giá trị này thay vì GIỮ 1 LẦN — làm hiển thị bị nhân lên N lần (N = số")
print("  dòng trùng). Cần sửa groupLines() ở sale_plan_controller.py và groupedLines() ở")
print("  delivery_planner_display_helpers_mixin.js: đổi qty_packed từ += sang giữ giá trị đầu")
print("  tiên, giống cách qty_warehouse_free đang được xử lý đúng.")
