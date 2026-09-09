# -*- coding: utf-8 -*-
"""
scan_orders_with_loyalty_account_amount_zero.py
================================================
Quét toàn bộ đơn bán hàng đang có cấu hình bảng "Tài khoản cộng điểm
Loyalty" (hlv.loyalty.sale.order.account.line) để tìm đơn có
earning_amount = 0 — tức là đơn TRƯỚC ĐÂY có nhập % cộng điểm (earning_pct,
field đã bị xoá khỏi model sau khi đổi thiết kế % → số tiền), nhưng SAU KHI
upgrade module earning_amount mặc định = 0 vì không tự quy đổi %→tiền được.
Những đơn này cần Sales/CSKH vào nhập lại SỐ TIỀN cộng điểm thủ công.

CHỈ ĐỌC — không write/create/unlink gì (kể cả câu SQL raw đọc cột
earning_pct cũ cũng chỉ SELECT).

Chạy bằng lệnh (trên Odoo.sh shell):
    python odoo-bin shell -d <TEN_DATABASE> < bin/scan_orders_with_loyalty_account_amount_zero.py
"""

SEP = "=" * 90
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")


section("1. Toàn bộ dòng phân bổ tài khoản Loyalty trên đơn bán hàng")
lines = env['hlv.loyalty.sale.order.account.line'].sudo().search([], order='order_id')
print(f"  Tổng số dòng: {len(lines)}")

# Đọc thêm cột earning_pct CŨ (nếu cột vẫn còn trong DB) để biết đơn nào
# trước đây đã từng cấu hình % - phòng khi cần tham khảo lại số cũ.
old_pct_by_line_id = {}
try:
    env.cr.execute(
        "SELECT id, earning_pct FROM hlv_loyalty_sale_order_account_line "
        "WHERE earning_pct IS NOT NULL AND earning_pct != 0"
    )
    old_pct_by_line_id = dict(env.cr.fetchall())
    print(f"  (Đọc thêm được cột earning_pct cũ từ DB: {len(old_pct_by_line_id)} dòng có giá trị != 0)")
except Exception as e:
    print(f"  (Không đọc được cột earning_pct cũ - có thể đã bị xoá khỏi DB: {e!r})")
    env.cr.rollback()

section("2. Đơn có earning_amount = 0 (CẦN NHẬP LẠI SỐ TIỀN)")
zero_lines = lines.filtered(lambda l: not l.earning_amount)
orders_needing_reentry = zero_lines.mapped('order_id')
print(f"  Số đơn cần rà lại: {len(orders_needing_reentry)}")
for order in orders_needing_reentry:
    print(f"\n  --- SO #{order.id} {order.name!r} state={order.state!r} partner={order.partner_id.display_name!r} ---")
    for l in order.loyalty_account_line_ids:
        old_pct = old_pct_by_line_id.get(l.id)
        old_pct_note = f" (earning_pct cũ = {old_pct!r})" if old_pct else ""
        flag = " <== earning_amount=0, CẦN NHẬP LẠI" if not l.earning_amount else ""
        print(
            f"      account={l.account_id.display_name!r} earning_amount={l.earning_amount!r}"
            f"{old_pct_note}{flag}"
        )

section("3. Đơn đã có earning_amount (không cần làm gì - liệt kê để đối chiếu)")
ok_lines = lines.filtered(lambda l: l.earning_amount)
orders_ok = ok_lines.mapped('order_id')
print(f"  Số đơn đã có số tiền: {len(orders_ok)}")
for order in orders_ok:
    print(f"  SO #{order.id} {order.name!r} state={order.state!r}: " + ", ".join(
        f"{l.account_id.display_name}={l.earning_amount:,.0f}đ" for l in order.loyalty_account_line_ids
    ))

section("4. Kết luận")
print(
    f"  => {len(orders_needing_reentry)} đơn cần Sales/CSKH mở lại, vào tab \n"
    "     'Tài khoản cộng điểm Loyalty', nhập SỐ TIỀN cộng điểm cho từng tài khoản.\n"
    "  => Sau khi nhập xong, nếu đơn ĐÃ CÓ phiếu xuất kho giao rồi, bấm nút\n"
    "     'Tạo bù điểm Loyalty' trên đơn để tạo bù điểm đổi thưởng còn thiếu."
)
