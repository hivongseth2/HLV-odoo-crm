# -*- coding: utf-8 -*-
"""
test_iot_print_reconcile.py
================================
KIỂM THỬ thuật toán đối chiếu 2 hàng đợi (Odoo đã gửi lệnh in vs máy in Windows thật sự đã in)
— xem stock_warehouse._iot_reconcile_printed_jobs().

Chạy 5 tình huống thực tế trên 1 kho THẬT nhưng dữ liệu là bản ghi hàng chờ in GIẢ do script tự
tạo, và ROLLBACK toàn bộ ở cuối (env.cr.rollback) nên KHÔNG để lại rác trong database:
  1. In đủ            -> tất cả 'printed_ok'
  2. In thiếu 2/3     -> 2 phiếu GỬI SAU CÙNG bị đánh 'suspect' (hàng đợi in là FIFO)
  3. Không in tờ nào  -> tất cả 'suspect'
  4. Chưa hết thời gian chờ (grace) -> KHÔNG kết luận, vẫn 'waiting'
  5. Counter tụt (Spooler restart)  -> tất cả 'suspect' (không xác nhận được)

⚠️ Script này CÓ ghi tạm vào database nhưng ROLLBACK ở cuối, không commit. Chạy trên staging.

Chạy bằng lệnh (trên Odoo.sh shell):
    python odoo-bin shell -d <TEN_DATABASE> < bin/test_iot_print_reconcile.py
"""

import json
from datetime import timedelta

from odoo import fields

SEP = "=" * 100
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

Warehouse = env['stock.warehouse'].sudo()
Queue = env['hlv.iot.print.queue'].sudo()

wh = Warehouse.search([], limit=1)
so = env['sale.order'].sudo().search([('state', 'in', ['sale', 'done'])], limit=1)
if not wh or not so:
    print("  Không có kho / đơn hàng nào để dựng dữ liệu test.")
else:
    grace = Warehouse._iot_verify_grace_minutes()
    print(f"  Kho test: {wh.name} (id={wh.id}) | đơn mẫu: {so.name} | grace = {grace} phút")

    def setup(printed_minutes_ago_list, counter_points):
        """Tạo n bản ghi 'đã gửi lệnh in' + lịch sử counter máy in. counter_points là list
        (số phút trước, giá trị counter)."""
        now = fields.Datetime.now()
        Queue.search([('warehouse_id', '=', wh.id), ('verify_note', '=', 'TEST_FIXTURE')]).unlink()
        # Vô hiệu hoá các bản ghi THẬT đang chờ đối chiếu của kho này để chúng không lẫn vào
        # phép tính của test (sẽ được rollback ở cuối, dữ liệu thật không đổi).
        Queue.search([('warehouse_id', '=', wh.id), ('state', '=', 'printed'),
                      ('verify_state', '=', 'waiting')]).write({'verify_state': 'no_data'})
        recs = Queue
        for mins in printed_minutes_ago_list:
            rec = Queue.create({
                'sale_order_id': so.id,
                'warehouse_id': wh.id,
                'state': 'printed',
                'printed_at': now - timedelta(minutes=mins),
                'verify_state': 'waiting',
                'verify_note': 'TEST_FIXTURE',
            })
            recs |= rec
        wh.x_iot_printed_counter_log = json.dumps([
            [fields.Datetime.to_string(now - timedelta(minutes=m)), v] for m, v in counter_points
        ])
        return recs.sorted('printed_at')

    def run(name, printed_minutes_ago_list, counter_points, counter_reset=False, expect=None):
        recs = setup(printed_minutes_ago_list, counter_points)
        # Xoá nhãn fixture để logic thật không lọc theo nó
        recs.write({'verify_note': False})
        wh._iot_reconcile_printed_jobs(counter_reset=counter_reset)
        got = [r.verify_state for r in recs.sorted('printed_at')]
        ok = 'ĐÚNG' if got == expect else 'SAI'
        print(f"\n  [{ok}] {name}")
        print(f"        kỳ vọng: {expect}")
        print(f"        thực tế: {got}")
        for r in recs.sorted('printed_at'):
            print(f"          - gửi lúc {r.printed_at} -> {r.verify_state}: {r.verify_note or ''}")
        recs.write({'verify_note': 'TEST_FIXTURE'})
        return ok == 'ĐÚNG'

    results = []
    section("Các tình huống")

    # 3 phiếu gửi cách đây 20/18/16 phút; counter: trước đó 60, sau đó 63 => in đủ 3
    results.append(run(
        'In đủ 3/3', [20, 18, 16],
        [(25, 60), (1, 63)],
        expect=['printed_ok', 'printed_ok', 'printed_ok'],
    ))

    # 3 phiếu, counter chỉ tăng 1 => 2 phiếu GỬI SAU bị nghi chưa in
    results.append(run(
        'In thiếu: gửi 3 mà máy chỉ in 1', [20, 18, 16],
        [(25, 60), (1, 61)],
        expect=['printed_ok', 'suspect', 'suspect'],
    ))

    # counter không tăng => cả 3 đều nghi chưa in
    results.append(run(
        'Máy in không in tờ nào', [20, 18, 16],
        [(25, 60), (1, 60)],
        expect=['suspect', 'suspect', 'suspect'],
    ))

    # phiếu vừa gửi 1 phút trước (chưa quá grace) => chưa kết luận
    results.append(run(
        f'Mới gửi 1 phút (grace {grace} phút) — chưa được kết luận', [1],
        [(25, 60), (0, 60)],
        expect=['waiting'],
    ))

    # Spooler restart (counter tụt) => nghi chưa in hết, để người xử lý quyết định
    results.append(run(
        'Spooler khởi động lại giữa đường', [20, 18],
        [(25, 60), (1, 5)],
        counter_reset=True,
        expect=['suspect', 'suspect'],
    ))

    section("KẾT QUẢ")
    print(f"  {sum(results)}/{len(results)} tình huống ĐÚNG")
    if all(results):
        print("  => Thuật toán đối chiếu hoạt động đúng như thiết kế.")
    else:
        print("  => CÓ TÌNH HUỐNG SAI, xem chi tiết phía trên.")

env.cr.rollback()
print("\n  Đã ROLLBACK toàn bộ dữ liệu test — database không bị thay đổi gì.")
