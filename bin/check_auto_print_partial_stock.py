# -*- coding: utf-8 -*-
"""
check_auto_print_partial_stock.py
==================================
Kho báo: phiếu lấy hàng CHƯA đủ hàng mà hệ thống vẫn tự gửi in (trên /sale_plan các đơn đó
hiện "Có hàng 1 phần" / "Có Hàng Chưa Đóng Gói" nhưng vẫn có cờ "Đã in").

Auto-print chỉ nhận phiếu ``state = 'assigned'`` và code đang ghi chú rằng assigned nghĩa là
"mọi move đã reserve ĐỦ" (xem models/stock_picking_auto_print.py). Script này kiểm tra xem
câu đó có đúng không, theo giả thuyết chính:

    stock.picking.state là field compute. Với loại hoạt động có ``move_type = 'direct'``
    ("Giao ngay khi có hàng"), Odoo đánh phiếu là 'assigned' NGAY KHI CHỈ CÓ MỘT PHẦN hàng
    được giữ. Chỉ ``move_type = 'one'`` ("Giao cùng lúc") mới giữ phiếu ở 'confirmed' cho
    tới khi đủ hết. Nếu loại hoạt động PICK của kho đang là 'direct' thì 'assigned' KHÔNG
    còn nghĩa là đủ hàng, và điều kiện lọc của auto-print sai ngay từ gốc.

Phần 3 là phần quyết định: đếm phiếu 'assigned' nhưng CÒN MOVE THIẾU, tách theo loại hoạt
động và move_type. Ra số lớn ở nhóm 'direct' là xác nhận giả thuyết.

Lưu ý: hàm chặn _pick_slip_stock_mismatch() hiện có KHÔNG bắt được ca này — nó so "phiếu ghi
lấy nhiều hơn tồn thực có", còn ở đây phiếu ghi lấy ÍT HƠN nhu cầu, tồn vẫn khớp.

CHỈ ĐỌC — không write/create/unlink gì.

Chạy bằng lệnh (trên Odoo.sh shell):
    python odoo-bin shell -d <TEN_DATABASE> --no-http < bin/check_auto_print_partial_stock.py
"""

# Các đơn trong thông báo lỗi máy in IoT gửi ra (đổi nếu cần soi đơn khác).
ORDER_NAMES = [
    'DH125524949236571', 'DH125524949236370', 'DH125524949236561',
    'DH125524949236336', 'DH125524949236622', 'DH125524949236634',
    'DH125524949236648', 'DH125524949236660', 'DH125524949236612',
    'DH125524949236675', 'DH125524949236685', 'DH125524949236703',
]

SEP = "=" * 100


def section(t):
    print(f"\n{SEP}\n  {t}\n{SEP}")


ICP = env['ir.config_parameter'].sudo()  # noqa: F821
Picking = env['stock.picking'].sudo()  # noqa: F821
Queue = env['hlv.iot.print.queue'].sudo()  # noqa: F821

PICK_DOMAIN = [
    ('picking_type_id.sequence_code', 'ilike', 'PICK'),
    ('return_id', '=', False),
]


def move_gap(picking):
    """Các move còn THIẾU hàng: (move, nhu cầu, đã giữ). Rỗng nghĩa là phiếu đủ hàng.

    So ``quantity`` (số kho sẽ lấy / đã giữ) với ``product_uom_qty`` (nhu cầu). Bỏ move đã
    huỷ. Dùng ngưỡng 0.001 để không báo lỗi vì sai số thập phân của đơn vị lẻ (mét, kg).
    """
    gaps = []
    for move in picking.move_ids:
        if move.state == 'cancel':
            continue
        if (move.product_uom_qty or 0) - (move.quantity or 0) > 0.001:
            gaps.append((move, move.product_uom_qty, move.quantity))
    return gaps


section("1) Setting auto-print")
for key in ('auto_print_pick_slip_when_full', 'lock_pick_slip_requests'):
    print(f"  {key:34s} = {ICP.get_param('hlv_sale_delivery_planning.' + key, default='(chưa set)')!r}")

section("2) Loại hoạt động PICK — move_type quyết định nghĩa của 'assigned'")
types = env['stock.picking.type'].sudo().with_context(active_test=False).search([  # noqa: F821
    ('sequence_code', 'ilike', 'PICK'),
])
print(f"  {'Loại hoạt động':<34} {'kho':<14} {'move_type':<10} {'nghĩa của assigned'}")
print(f"  {'-' * 96}")
for ptype in types:
    wh = ptype.warehouse_id
    if ptype.move_type == 'direct':
        meaning = "CÓ MỘT PHẦN HÀNG LÀ ĐÃ 'Sẵn sàng'  <-- nguồn của bug"
    else:
        meaning = "chỉ 'Sẵn sàng' khi đủ hết hàng"
    print(f"  {(ptype.name or '')[:33]:<34} {(wh.name or '-')[:13]:<14} {ptype.move_type or '-':<10} {meaning}")

section("3) PHẦN QUYẾT ĐỊNH — phiếu 'Sẵn sàng' nhưng còn move thiếu hàng")
assigned = Picking.search(PICK_DOMAIN + [('state', '=', 'assigned')])
print(f"  Tổng phiếu PICK đang 'Sẵn sàng': {len(assigned)}")
buckets = {}
for pick in assigned:
    ptype = pick.picking_type_id
    key = (ptype.name or '?', ptype.move_type or '?')
    stats = buckets.setdefault(key, {'du': 0, 'thieu': 0, 'thieu_da_in': 0, 'vi_du': []})
    if move_gap(pick):
        stats['thieu'] += 1
        if pick.x_printed:
            stats['thieu_da_in'] += 1
        if len(stats['vi_du']) < 5:
            stats['vi_du'].append(pick)
    else:
        stats['du'] += 1
print(f"\n  {'Loại hoạt động':<30} {'move_type':<10} {'ĐỦ hàng':>8} {'THIẾU':>7} {'thiếu mà ĐÃ IN':>16}")
print(f"  {'-' * 96}")
for (name, move_type), stats in sorted(buckets.items(), key=lambda kv: -kv[1]['thieu']):
    print(f"  {name[:29]:<30} {move_type:<10} {stats['du']:>8} {stats['thieu']:>7} {stats['thieu_da_in']:>16}")

for (name, move_type), stats in buckets.items():
    if not stats['vi_du']:
        continue
    print(f"\n  Ví dụ phiếu THIẾU nhưng vẫn 'Sẵn sàng' — {name} ({move_type}):")
    for pick in stats['vi_du']:
        gaps = move_gap(pick)
        print(f"    {pick.name:22s} x_printed={str(pick.x_printed):5s} "
              f"auto_gui_in={str(pick.x_auto_print_requested):5s} thiếu {len(gaps)}/{len(pick.move_ids)} dòng")
        for move, demand, reserved in gaps[:3]:
            print(f"        {(move.product_id.default_code or move.product_id.name or '')[:30]:<32} "
                  f"cần={demand:>9.2f} giữ được={reserved:>9.2f} thiếu={demand - reserved:>9.2f}")

section("4) Các đơn trong thông báo lỗi máy in — soi từng phiếu")
for name in ORDER_NAMES:
    order = env['sale.order'].sudo().search([('name', '=', name)], limit=1)  # noqa: F821
    if not order:
        print(f"  {name}: KHÔNG tìm thấy đơn")
        continue
    picks = order.picking_ids.filtered(
        lambda p: 'PICK' in (p.picking_type_id.sequence_code or '').upper() and not p.return_id
    )
    if not picks:
        print(f"  {name}: không có phiếu PICK")
        continue
    for pick in picks:
        gaps = move_gap(pick)
        verdict = 'ĐỦ' if not gaps else 'THIẾU %d dòng' % len(gaps)
        qs = Queue.search(['|', ('sale_order_id', '=', order.id), ('picking_ids', 'in', [pick.id])])
        # Bản ghi hàng chờ nào do HỆ THỐNG tự gửi: chatter của nó có chữ "tự động"
        # (xem iot_print_queue.create) — đây là cách phân biệt sale bấm tay vs cron gửi.
        auto_marks = []
        for q in qs:
            bodies = ' '.join(env['mail.message'].sudo().search([  # noqa: F821
                ('model', '=', 'hlv.iot.print.queue'), ('res_id', '=', q.id),
            ]).mapped(lambda m: m.body or ''))
            auto_marks.append('%s#%s%s' % (
                q.state, q.id, ' (TỰ ĐỘNG)' if 'tự động' in bodies else ' (sale bấm)',
            ))
        print(f"  {name}  {pick.name:22s} state={pick.state:10s} {verdict:16s} "
              f"x_printed={str(pick.x_printed):5s} hàng_chờ=[{', '.join(auto_marks) or '-'}]")
        for move, demand, reserved in gaps[:3]:
            print(f"      thiếu: {(move.product_id.default_code or move.product_id.name or '')[:30]:<32} "
                  f"cần={demand:>9.2f} giữ được={reserved:>9.2f}")

section("ĐỌC KẾT QUẢ")
print("  - Phần 2 ra move_type='direct' cho loại PICK của kho, VÀ phần 3 có phiếu ở cột THIẾU")
print("    -> xác nhận: 'assigned' KHÔNG có nghĩa đủ hàng, điều kiện lọc của auto-print sai.")
print("       Sửa: thêm điều kiện mọi move phải có quantity >= product_uom_qty (đúng như câu")
print("       hứa của setting: 'giữ ĐỦ hàng cho TẤT CẢ sản phẩm'), đừng tin state.")
print("  - Cột 'thiếu mà ĐÃ IN' là số phiếu đã ra giấy trong khi còn thiếu hàng — đây chính là")
print("    số tờ kho đã cầm đi lấy hàng không có.")
print("  - Phần 4 ghi rõ từng phiếu do TỰ ĐỘNG gửi hay sale bấm tay: nếu toàn bộ là (TỰ ĐỘNG)")
print("    thì lỗi nằm ở cron, không phải do sale bấm nhầm.")
print("  - Phần 3 KHÔNG có phiếu nào ở cột THIẾU -> giả thuyết sai, phải tìm hướng khác:")
print("    xem lại thời điểm in so với thời điểm unreserve (phiếu lúc in thì đủ, sau đó bị")
print("    nhả hàng cho phiếu khác), bằng x_pick_print_end_at so với chatter của phiếu.")
