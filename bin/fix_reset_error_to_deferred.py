#!/usr/bin/env python3
"""
Reset tất cả queue records ở trạng thái ERROR về DEFERRED.

Mục đích:
  - Hôm nay là Chủ nhật (ngoài khung giờ). Cron cũ không có kiểm tra CN
    nên đã retry các đơn error liên tục → tất cả bị InvalidInvoiceDate.
  - Sau khi reset về deferred, sáng T2 khi code mới deploy + cron chạy
    trong window (07:00-16:30), nó sẽ tự reset deferred → pending rồi
    xử lý với inv_date = ngày T2 (auto-update trong _process_one).

Cách chạy:
    python odoo-bin shell -d <database> --no-http < bin/fix_reset_error_to_deferred.py

Lưu ý: Script này THAY ĐỔI dữ liệu thật. Chạy xong sẽ commit.
"""
import pytz
from datetime import datetime

env = env  # noqa: F821

tz = pytz.timezone('Asia/Ho_Chi_Minh')
now_local = datetime.now(tz)
print(f'\n[{now_local.strftime("%d/%m/%Y %H:%M:%S")}] Fix: reset queue error → deferred')
print('=' * 60)

# ── Tìm tất cả error records ────────────────────────────────────
error_queues = env['amis.webhook.queue'].sudo().search([
    ('state', '=', 'error'),
])

if not error_queues:
    print('Không có record nào ở trạng thái error.')
else:
    print(f'Tìm thấy {len(error_queues)} record error:')
    for q in error_queues:
        so_name = q.sale_order_id.name if q.sale_order_id else (q.order_ref or '?')
        print(f'  [{q.id}] {so_name:<10}  attempts={q.attempts}  lỗi: {(q.error_msg or "")[:60]}')

    confirm = input(f'\nReset {len(error_queues)} record về DEFERRED? (y/n): ').strip().lower()
    if confirm != 'y':
        print('Đã hủy.')
    else:
        error_queues.sudo().write({
            'state': 'deferred',
            'error_msg': 'Reset thủ công về deferred ngày %s. Sẽ tự xử lý sáng T2 trong khung giờ.'
                         % now_local.strftime('%d/%m/%Y %H:%M'),
            'attempts': 0,   # reset về 0 để có 3 lần thử mới
        })
        env.cr.commit()
        print(f'\n✓ Đã reset {len(error_queues)} record về deferred.')
        print('  Sáng T2 khi cron chạy trong 07:00-16:30 sẽ tự xử lý lại.')
        print('  inv_date sẽ tự update = ngày gửi thật (code mới trong _process_one).')

# ── Kiểm tra lại ───────────────────────────────────────────────
remaining_errors = env['amis.webhook.queue'].sudo().search([('state', '=', 'error')])
deferred_count = env['amis.webhook.queue'].sudo().search_count([('state', '=', 'deferred')])
print(f'\n[Sau reset]')
print(f'  error còn lại : {len(remaining_errors)}')
print(f'  deferred      : {deferred_count}')
print('=' * 60)
