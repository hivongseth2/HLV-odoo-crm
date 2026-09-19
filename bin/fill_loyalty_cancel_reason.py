# -*- coding: utf-8 -*-
"""
fill_loyalty_cancel_reason.py
==============================
Điền `cancel_reason` cho các bản ghi hlv.loyalty.history ĐÃ BỊ HỦY TRƯỚC KHI
field này tồn tại.

Vì sao cần: `stock.picking._get_loyalty_earn_plan` dựa vào `cancel_reason` để
biết bản ghi điểm đổi thưởng đã hủy là do HOÀN HÀNG (không được tích lại — hàng
đã trả) hay do người dùng CHỦ ĐỘNG THU HỒI (được phép tích lại). Bản ghi cũ có
`cancel_reason` rỗng sẽ bị coi như "hủy do hoàn hàng", nên nút "Tạo bù điểm
Loyalty" luôn hiện 0 điểm dù đã thu hồi.

Cách nhận diện (chỉ dùng cho dữ liệu cũ, dữ liệu mới đã tự ghi đúng):
    - mô tả chứa '[Hủy do hoàn hàng'  -> 'return'
    - còn lại                          -> 'revoke' (hủy/thu hồi thủ công)

CHỈ ghi vào field `cancel_reason`, KHÔNG đụng tới state/điểm/mô tả.

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/fill_loyalty_cancel_reason.py
"""

SEP = "=" * 90
print(f"\n{SEP}\n  ĐIỀN LÝ DO HỦY CHO BẢN GHI ĐIỂM ĐÃ HỦY\n{SEP}")

History = env['hlv.loyalty.history'].sudo()
targets = History.search([
    ('state', '=', 'cancelled'),
    ('cancel_reason', '=', False),
])
print(f"  Số bản ghi đã hủy nhưng chưa có lý do: {len(targets)}")

if not targets:
    print("  => Không có gì để cập nhật.")
else:
    by_return = targets.filtered(
        lambda h: '[Hủy do hoàn hàng' in (h.description or '')
    )
    by_revoke = targets - by_return

    for record in targets:
        reason = 'return' if record in by_return else 'revoke'
        print(
            f"    #{record.id} {record.point_type!r} {record.point_amount} điểm"
            f" | SO={record.sale_order_id.name or '-'}"
            f" | TK={record.account_id.display_name!r} -> {reason}"
        )

    if by_return:
        by_return.write({'cancel_reason': 'return'})
    if by_revoke:
        by_revoke.write({'cancel_reason': 'revoke'})
    env.cr.commit()

    print(
        f"\n  => Đã cập nhật: {len(by_return)} bản ghi 'Hoàn hàng',"
        f" {len(by_revoke)} bản ghi 'Thu hồi thủ công'."
    )
    print(
        "  Các bản ghi 'Thu hồi thủ công' giờ có thể được tạo lại qua nút\n"
        "  \"Tạo bù điểm Loyalty\" trên đơn bán hàng."
    )
