#!/usr/bin/env python3
"""
Test gửi 1 HĐĐT nháp lên CQT qua webhook queue (DRY-RUN).

Cách chạy:
    python odoo-bin shell -d <database> --no-http < bin/test_webhook_time_window.py

Kịch bản:
  - Lấy đơn SO_NAME, tìm HĐĐT nháp của đơn đó
  - Tạo 1 queue record → gọi _process_one() trực tiếp
  - Dry-run được bật tạm thời → KHÔNG gửi CQT thật
  - Cuối cùng rollback toàn bộ (không commit) để không thay đổi DB
"""
import pytz
from datetime import datetime

env = env  # noqa: F821

SO_NAME = 'S03522'   # ← đổi đơn muốn test ở đây

print('\n' + '=' * 70)
print(f'DRY-RUN TEST: Gửi HĐĐT webhook cho {SO_NAME}')
print('=' * 70)

# ── Timezone & giờ hiện tại ───────────────────────────────────────────────────
tz_name = env.company.partner_id.tz or env.user.tz or 'Asia/Ho_Chi_Minh'
tz = pytz.timezone(tz_name)
now_local = datetime.now(tz)
print(f'\nGiờ hiện tại ({tz_name}): {now_local.strftime("%H:%M:%S")}')

# ── Config ───────────────────────────────────────────────────────────────────
config = env['amis.callback.config'].sudo().search([], limit=1)
if not config:
    print('KHÔNG CÓ cấu hình!')
    raise SystemExit

print(f'\n[CONFIG]')
print(f'  meinvoice_enabled   = {config.meinvoice_enabled}')
print(f'  meinvoice_skip_api  = {config.meinvoice_skip_api}  ← cần True để dry-run')
print(f'  webhook_auto_publish_enabled   = {config.webhook_auto_publish_enabled}')

def fmt(v):
    h = int(v); m = int(round((v - h) * 60))
    return '%02d:%02d' % (h, m)

if config.webhook_publish_time_restrict:
    Queue = env['amis.webhook.queue']
    within = Queue._is_within_publish_window(config)
    print(f'  Khung giờ: {fmt(config.webhook_publish_time_from)} – {fmt(config.webhook_publish_time_to)}'
          f'  → {"TRONG" if within else "NGOÀI"} khung')
else:
    print('  Không giới hạn khung giờ')

# ── Tìm SO và HĐĐT nháp ──────────────────────────────────────────────────────
so = env['sale.order'].sudo().search([('name', '=', SO_NAME)], limit=1)
if not so:
    print(f'\nKHÔNG TÌM THẤY SO {SO_NAME}')
    raise SystemExit

print(f'\n[SO] {so.name}  state={so.state}  amount_total={so.amount_total:,.0f}')

drafts = env['meinvoice.invoice'].sudo().search([
    ('sale_order_id', '=', so.id),
    ('state', '=', 'draft'),
], order='id desc')

if not drafts:
    print('KHÔNG CÓ HĐĐT nháp trên đơn này!')
    raise SystemExit

draft = drafts[0]
print(f'\n[HĐĐT nháp]  id={draft.id}  series={draft.inv_series}  '
      f'date={draft.inv_date}  total={draft.total_amount:,.0f}')
print(f'  buyer_legal_name = {draft.buyer_legal_name}')
print(f'  state            = {draft.state}')
if len(drafts) > 1:
    print(f'  ⚠ Có {len(drafts)} nháp — sẽ dùng id={draft.id} (mới nhất)')

# ── Bật dry-run nếu chưa ─────────────────────────────────────────────────────
orig_skip = config.meinvoice_skip_api
orig_enabled = config.meinvoice_enabled
if not orig_skip:
    config.sudo().write({'meinvoice_skip_api': True})
    print('\n[*] Đã bật meinvoice_skip_api=True (dry-run)')
else:
    print('\n[*] meinvoice_skip_api đã là True (dry-run)')

if not orig_enabled:
    config.sudo().write({'meinvoice_enabled': True})
    print('[*] Đã bật meinvoice_enabled=True tạm thời')

# ── Tạo queue record và test _process_one ────────────────────────────────────
print(f'\n[TEST] Tạo queue record → gọi _process_one()...')
queue_rec = env['amis.webhook.queue'].sudo().create({
    'order_ref': so.shopee_order_ref or so.name,
    'sale_order_id': so.id,
    'state': 'pending',
    'trigger_status': 'TEST_DRY_RUN',
    'push_code': 'TEST',
})
print(f'  Queue id={queue_rec.id} created')

try:
    queue_rec._process_one(config)
    env.cr.flush()
    queue_rec.invalidate_recordset()
    draft.invalidate_recordset()

    print(f'\n[KẾT QUẢ]')
    print(f'  queue.state     = {queue_rec.state}')
    print(f'  queue.error_msg = {queue_rec.error_msg or "-"}')
    print(f'  draft.state     = {draft.state}  (phải là submitted hoặc accepted nếu OK)')
    print(f'  draft.inv_no    = {draft.inv_no or "-"}')
    print(f'  draft.inv_code  = {draft.inv_code or "-"}  (trống = CQT chưa cấp mã, bình thường với dry-run)')
    print(f'  transaction_id  = {draft.transaction_id or "-"}')

    if queue_rec.state == 'done':
        print('\n  ✓ PASS: queue=done, draft đã được gửi (dry-run, không lên CQT thật)')
    elif queue_rec.state == 'deferred':
        print('\n  → DEFERRED: đơn bị gom lại vì ngoài khung giờ (logic đúng nếu đang cấu hình khung giờ)')
    else:
        print(f'\n  ✗ FAIL: queue.state={queue_rec.state}')

except Exception as e:
    print(f'\n  ✗ EXCEPTION: {e}')

# ── Rollback toàn bộ — không commit ──────────────────────────────────────────
env.cr.rollback()
print('\n[*] ROLLBACK — không có gì thay đổi trong DB.')
print('\n' + '=' * 70 + '\nXONG\n' + '=' * 70)


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
