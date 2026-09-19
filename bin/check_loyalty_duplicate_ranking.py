# -*- coding: utf-8 -*-
"""
check_loyalty_duplicate_ranking.py
===================================
Rà soát các phiếu xuất kho bị ĐẾM ĐÔI điểm xếp hạng: tổng điểm xếp hạng đã ghi
cho 1 phiếu (mọi tài khoản, bỏ bản ghi đã hủy) LỚN HƠN số điểm xếp hạng đúng
của phiếu đó.

Nguyên nhân: điểm xếp hạng được tính 1 lần cho cả phiếu rồi chia cho các tài
khoản, nhưng cơ chế chống trùng cũ khóa theo `account_id`. Khi bảng "Tài khoản
cộng điểm Loyalty" trên đơn bị SỬA sang tài khoản khác rồi chạy lại tích điểm
(validate lại / wizard tính lại / nút "Tạo bù điểm Loyalty"), tài khoản mới
nhận thêm nguyên một bộ điểm xếp hạng trong khi bản ghi của tài khoản cũ đã
confirmed vẫn nằm lại.

CHỈ ĐỌC — không write/create/unlink gì.

Chạy trên máy có Odoo (Odoo.sh shell hoặc server):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_loyalty_duplicate_ranking.py
"""

from collections import defaultdict

# Đặt = 0 để quét toàn bộ lịch sử; đặt số ngày để chỉ quét gần đây cho nhanh.
DAYS_BACK = 0

SEP = "=" * 90
print(f"\n{SEP}\n  RÀ SOÁT ĐIỂM XẾP HẠNG BỊ ĐẾM ĐÔI\n{SEP}")

program = env['hlv.loyalty.program'].sudo().search([('active', '=', True)], limit=1)
if not program:
    print("  KHÔNG có chương trình loyalty active -> không tính lại được.")
    raise SystemExit()
print(f"  Program #{program.id} earning_amount={program.earning_amount} earning_points={program.earning_points}")

domain = [
    ('transaction_type', '=', 'earn'),
    ('point_type', '=', 'ranking'),
    ('state', '!=', 'cancelled'),
    ('picking_id', '!=', False),
]
if DAYS_BACK:
    from odoo import fields as odoo_fields
    from datetime import timedelta
    domain.append(('create_date', '>=', odoo_fields.Datetime.now() - timedelta(days=DAYS_BACK)))

hist = env['hlv.loyalty.history'].sudo().search(domain)
print(f"  Tổng bản ghi điểm xếp hạng đang xét: {len(hist)}")

by_picking = defaultdict(list)
for h in hist:
    by_picking[h.picking_id].append(h)

# Chỉ phiếu có từ 2 TÀI KHOẢN trở lên mới có khả năng bị đếm đôi; phiếu 1 tài
# khoản đã được cơ chế chống trùng theo account_id chặn từ trước.
suspects = {
    picking: records for picking, records in by_picking.items()
    if len({r.account_id.id for r in records}) >= 2
}
print(f"  Phiếu có >= 2 tài khoản nhận điểm xếp hạng (cần đối chiếu): {len(suspects)}\n")

bad = []
for picking, records in suspects.items():
    recorded = sum(r.point_amount for r in records)
    try:
        delivered_lines = picking._get_loyalty_delivered_lines()
        delivered_subtotal = sum(
            (l['price_unit'] or 0.0) * (l['qty'] or 0.0) for l in delivered_lines
        )
    except Exception as e:
        print(f"  !! Không tính lại được phiếu {picking.name!r}: {e!r}")
        continue

    expected = 0
    if delivered_subtotal > 0 and program.earning_amount > 0:
        expected = int(delivered_subtotal / program.earning_amount) * program.earning_points

    if recorded > expected:
        bad.append((picking, records, recorded, expected))

if not bad:
    print("  => KHÔNG phát hiện phiếu nào bị đếm đôi điểm xếp hạng.")
else:
    print(f"  => PHÁT HIỆN {len(bad)} phiếu bị đếm đôi:\n")
    total_excess = 0
    for picking, records, recorded, expected in sorted(bad, key=lambda x: x[0].name or ''):
        excess = recorded - expected
        total_excess += excess
        so_name = picking.sale_id.name if picking.sale_id else '(không có SO)'
        print(
            f"  Phiếu {picking.name!r} (SO {so_name}): đã ghi {recorded} điểm, "
            f"đúng phải {expected} điểm -> DƯ {excess} điểm"
        )
        for r in sorted(records, key=lambda x: x.id):
            print(
                f"      history #{r.id} account={r.account_id.display_name!r} "
                f"point_amount={r.point_amount} state={r.state!r} create_date={r.create_date}"
            )
    print(f"\n  TỔNG ĐIỂM XẾP HẠNG DƯ TRÊN TOÀN HỆ THỐNG: {total_excess}")
    print(
        "\n  Cách xử lý (làm thủ công, script này KHÔNG tự sửa):\n"
        "    - Với mỗi phiếu ở trên, giữ lại bản ghi của tài khoản ĐÚNG theo bảng\n"
        "      'Tài khoản cộng điểm Loyalty' hiện tại trên đơn, hủy/điều chỉnh các\n"
        "      bản ghi xếp hạng của tài khoản cũ cho tới khi tổng khớp cột 'đúng phải'.\n"
        "    - Code đã được vá (stock_picking._loyalty_earn_points chốt trần tổng điểm\n"
        "      xếp hạng theo phiếu) nên từ nay chạy lại tích điểm sẽ không sinh thêm."
    )
