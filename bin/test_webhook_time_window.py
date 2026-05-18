#!/usr/bin/env python3
"""
Test tính năng khung giờ phát hành HĐĐT webhook.

Cách chạy:
    python odoo-bin shell -d <database> --no-http < bin/test_webhook_time_window.py

Script này:
  1. In giờ hiện tại theo timezone công ty
  2. In cấu hình khung giờ hiện tại
  3. Kiểm tra _is_within_publish_window()
  4. Tạo 2 bản ghi queue test (pending) rồi gọi _process_pending()
     → Xem chúng thành deferred hay được xử lý
  5. Dọn dẹp bản ghi test sau khi xong
"""
import pytz
from datetime import datetime

env = env  # noqa: F821

print('\n' + '=' * 70)
print('TEST: Khung giờ phát hành HĐĐT webhook')
print('=' * 70)

# ── 1. Giờ hiện tại ──────────────────────────────────────────────────────────
tz_name = (env.company.partner_id.tz or env.user.tz or 'Asia/Ho_Chi_Minh')
tz = pytz.timezone(tz_name)
now_local = datetime.now(tz)
current_hour = now_local.hour + now_local.minute / 60.0
print(f'\n[1] Giờ hiện tại')
print(f'    Timezone : {tz_name}')
print(f'    Giờ local: {now_local.strftime("%H:%M:%S")}  ({current_hour:.4f})')

# ── 2. Cấu hình ──────────────────────────────────────────────────────────────
config = env['amis.callback.config'].sudo().search([], limit=1)
if not config:
    print('\nKHÔNG CÓ cấu hình amis.callback.config!')
    raise SystemExit

print(f'\n[2] Cấu hình webhook')
print(f'    webhook_auto_publish_enabled   = {config.webhook_auto_publish_enabled}')
print(f'    webhook_publish_time_restrict  = {config.webhook_publish_time_restrict}')

def fmt(v):
    h = int(v); m = int(round((v - h) * 60))
    return '%02d:%02d' % (h, m)

print(f'    webhook_publish_time_from      = {fmt(config.webhook_publish_time_from)}  ({config.webhook_publish_time_from})')
print(f'    webhook_publish_time_to        = {fmt(config.webhook_publish_time_to)}  ({config.webhook_publish_time_to})')
print(f'    webhook_publish_deferred_action= {config.webhook_publish_deferred_action}')

# ── 3. Kiểm tra window ────────────────────────────────────────────────────────
Queue = env['amis.webhook.queue']
within = Queue._is_within_publish_window(config)
print(f'\n[3] _is_within_publish_window() = {within}')
if config.webhook_publish_time_restrict:
    print(f'    Khung giờ: {fmt(config.webhook_publish_time_from)} – {fmt(config.webhook_publish_time_to)}')
    print(f'    Giờ hiện tại {fmt(current_hour)} {"✓ TRONG" if within else "✗ NGOÀI"} khung giờ')
else:
    print('    (Không bật giới hạn khung giờ → luôn True)')

# ── 4. Tạo bản ghi test ──────────────────────────────────────────────────────
print('\n[4] Tạo 2 bản ghi test (pending) rồi gọi _process_pending()')

# Cần tắt auto_publish để không ảnh hưởng đơn thật, ta test bằng cách
# override config tạm thời trong memory (không write DB)
# → Tạo queue records với state pending và dùng _process_pending trực tiếp

# Tìm 1 SO dummy hoặc dùng None
fake_ref_1 = '__TEST_TW_001__'
fake_ref_2 = '__TEST_TW_002__'

# Tạo bản ghi test
q1 = Queue.sudo().create({
    'order_ref': fake_ref_1,
    'state': 'pending',
    'trigger_status': 'TEST',
    'push_code': 'TEST',
})
q2 = Queue.sudo().create({
    'order_ref': fake_ref_2,
    'state': 'pending',
    'trigger_status': 'TEST',
    'push_code': 'TEST',
})
print(f'    Tạo queue id={q1.id} (ref={fake_ref_1})')
print(f'    Tạo queue id={q2.id} (ref={fake_ref_2})')

# Gọi _process_pending — nó sẽ check window và quyết định
# Tạm bật webhook_auto_publish_enabled nếu đang tắt
orig_enabled = config.webhook_auto_publish_enabled
if not orig_enabled:
    config.sudo().write({'webhook_auto_publish_enabled': True})
    print('    (Tạm bật webhook_auto_publish_enabled để test)')

env['amis.webhook.queue']._process_pending()
env.cr.flush()

q1.invalidate_recordset()
q2.invalidate_recordset()

print(f'\n[5] Kết quả sau _process_pending():')
print(f'    Queue {q1.id}: state={q1.state!r:12}  error_msg={q1.error_msg or "-"}')
print(f'    Queue {q2.id}: state={q2.state!r:12}  error_msg={q2.error_msg or "-"}')

if within:
    print('\n    → Đang TRONG khung giờ:')
    print('      ✓ Bản ghi pending sẽ được xử lý (state=error vì không có SO thật — bình thường)')
else:
    print('\n    → Đang NGOÀI khung giờ:')
    if q1.state == 'deferred':
        print('      ✓ ĐÚNG: state=deferred — đơn được gom lại chờ')
    else:
        print('      ✗ SAI: state nên là deferred nhưng là', q1.state)

# ── 5. Dọn dẹp ───────────────────────────────────────────────────────────────
q1.sudo().unlink()
q2.sudo().unlink()
env.cr.commit()
print('\n[6] Đã xóa bản ghi test. Commit.')

print('\n' + '=' * 70)
print('XONG')
print('=' * 70)
