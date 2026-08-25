# -*- coding: utf-8 -*-
"""
check_pick_unreserve_notify_gap.py
===================================
User xóa 1 dòng move line (ID 223454) trên phiếu TSN/PICK/16456 (liên kết đơn bán S07354) —
log server xác nhận stock.move.line đã bị unlink() thật, nhưng KHÔNG thấy Zalo được gửi, cũng
không thấy log lỗi nào (_notify_sale_pick_unreserved trong website_public_inventory_18/models/
stock_picking.py chỉ log lỗi khi send_hold_unreserve_notification() raise exception — nếu code
chỉ lặng lẽ "continue" vì thiếu dữ liệu, sẽ KHÔNG có log gì cả).

Nghi ngờ chính: SO S07354 không có giá trị ở field x_studio_misa_saler_code (mã sale MISA) —
_notify_sale_pick_unreserved() có dòng "if not saler_code: continue" bỏ qua ÂM THẦM, không log
gì hết. Script này kiểm tra trực tiếp để xác nhận hoặc loại trừ giả thuyết này, và kiểm tra luôn
các điều kiện còn lại (is_stock_hold_picking, sequence_code, config Zalo, mapping).

CHỈ ĐỌC — không write/create/unlink gì.

Chạy bằng lệnh (trên Odoo.sh shell, hoặc odoo-bin shell tại môi trường đang chạy):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_pick_unreserve_notify_gap.py
"""

SEP = "=" * 90
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

section("1. Phiếu TSN/PICK/16456 — các điều kiện mà _notify_sale_pick_unreserved() kiểm tra")
picking = env['stock.picking'].sudo().search([('name', '=', 'TSN/PICK/16456')], limit=1)
if not picking:
    print("  KHÔNG tìm thấy phiếu TSN/PICK/16456 (có thể tên khác đi do sequence) — thử tìm theo origin S07354:")
    picking = env['stock.picking'].sudo().search([('origin', '=', 'S07354')], limit=5)
    for p in picking:
        print(f"    - {p.name} (id={p.id}, state={p.state})")
    picking = picking[:1]

if picking:
    p = picking[0]
    print(f"  Tên phiếu: {p.name} (id={p.id})")
    print(f"  State: {p.state}")
    print(f"  is_stock_hold_picking: {p.is_stock_hold_picking}")
    print(f"  picking_type_id: {p.picking_type_id.name} (sequence_code={p.picking_type_id.sequence_code!r})")
    print(f"  sale_id: {p.sale_id.name if p.sale_id else '(KHÔNG có)'}")
    so = p.sale_id
    if so:
        saler_code = getattr(so, 'x_studio_misa_saler_code', '<<FIELD KHÔNG TỒN TẠI>>')
        print(f"  sale_id.x_studio_misa_saler_code: {saler_code!r}")
        print(f"  sale_id.user_id (Salesperson Odoo): {so.user_id.name if so.user_id else '(KHÔNG có)'}")
    print(f"  move_ids sản phẩm: {', '.join(p.move_ids.mapped('product_id.display_name'))}")
    print(f"  move_line_ids hiện tại: {p.move_line_ids.ids}")
else:
    print("  Không tìm được phiếu nào để kiểm tra tiếp — dừng ở đây.")

section("2. Config Zalo Stock Notification đang active")
config = env['hlv.zalo.stock.notification'].sudo()._get_active_config()
if not config:
    print("  KHÔNG có config nào đang active=True! -> Mọi thông báo Zalo (giữ hàng lẫn PICK) đều bị bỏ qua.")
else:
    print(f"  Config active: #{config.id} - {config.name}")
    print(f"  use_shared_token: {config.use_shared_token}")
    raw = config.hold_unreserve_saler_mapping_text or ''
    print(f"  hold_unreserve_saler_mapping_text (raw):\n{raw or '  (RỖNG — chưa cấu hình dòng nào)'}")
    if picking and picking[0].sale_id:
        so = picking[0].sale_id
        saler_code = getattr(so, 'x_studio_misa_saler_code', False)
        if saler_code:
            uids = config.get_hold_unreserve_saler_user_ids_from_mapping(saler_code)
            print(f"  Tra mapping với saler_code={saler_code!r} -> user_ids={uids}")
        else:
            print("  Không tra được mapping vì saler_code rỗng/không tồn tại trên SO này.")

section("3. Kiểm tra field x_studio_misa_saler_code có tồn tại trên model sale.order không")
SO = env['sale.order']
print(f"  'x_studio_misa_saler_code' in SO._fields: {'x_studio_misa_saler_code' in SO._fields}")
if 'x_studio_misa_saler_code' in SO._fields:
    f = SO._fields['x_studio_misa_saler_code']
    print(f"  Kiểu field: {type(f).__name__}, string={f.string!r}")

section("4. Thử log server gần đây có dòng nào từ module mình không (grep gợi ý, không tự chạy được ở đây)")
print("  Không thể grep log server từ trong shell này — anh tự grep trên server log với các từ khóa:")
print("    'Lỗi gửi Zalo (PICK unreserve)'")
print("    '_notify_sale_pick_unreserved'")
print("  Nếu KHÔNG thấy dòng nào cả (kể cả lỗi) thì khả năng cao nhất là do saler_code rỗng ở mục 1/2 trên.")

section("XONG")
print("  Gửi lại toàn bộ output — đặc biệt mục 1 (saler_code) và mục 2 (mapping) — để biết")
print("  chính xác code có chạy tới đúng chỗ hay bị 'continue' âm thầm vì thiếu dữ liệu.")
