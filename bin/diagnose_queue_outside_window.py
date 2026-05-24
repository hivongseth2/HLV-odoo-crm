#!/usr/bin/env python3
"""
Chẩn đoán tại sao queue được xử lý ngoài khung giờ.

Cách chạy:
    python odoo-bin shell -d <database> --no-http < bin/diagnose_queue_outside_window.py
"""
import pytz
from datetime import datetime, date

env = env  # noqa: F821

CHECK_SOS = ['S03644', 'S03622', 'S03648', 'S03704']

print('\n' + '=' * 75)
print('CHẨN ĐOÁN: Queue xử lý ngoài khung giờ')
print('=' * 75)

# ── Config ───────────────────────────────────────────────────────────────────
config = env['amis.callback.config'].sudo().search([], limit=1)
tz_name = env.company.partner_id.tz or env.user.tz or 'Asia/Ho_Chi_Minh'
tz = pytz.timezone(tz_name)
now_local = datetime.now(tz)

print(f'\n[CONFIG]')
print(f'  webhook_auto_publish_enabled  = {config.webhook_auto_publish_enabled}')
print(f'  webhook_publish_time_restrict = {config.webhook_publish_time_restrict}')

def fmt(v):
    h = int(v); m = int(round((v - h) * 60))
    return '%02d:%02d' % (h, m)

if config.webhook_publish_time_restrict:
    print(f'  Khung giờ : {fmt(config.webhook_publish_time_from)} – {fmt(config.webhook_publish_time_to)}')
    print(f'  Hành động : {config.webhook_publish_deferred_action}')

# ── Kiểm tra từng SO ─────────────────────────────────────────────────────────
print(f'\n[QUEUE RECORDS]')
print(f'  {"SO":<10} {"Nhận lúc (local)":<22} {"Gửi lúc (local)":<18} {"Trong window?":>14} {"State":<12} {"Attempts":>8}  Lỗi')
print(f'  {"─" * 115}')

for so_name in CHECK_SOS:
    so = env['sale.order'].sudo().search([('name', '=', so_name)], limit=1)
    if not so:
        print(f'  {so_name:<10} KHÔNG TÌM THẤY SO')
        continue

    queues = env['amis.webhook.queue'].sudo().search(
        [('sale_order_id', '=', so.id)], order='create_date asc'
    )
    if not queues:
        print(f'  {so_name:<10} Không có queue record')
        continue

    for q in queues:
        # create_date là UTC, convert sang local
        create_utc = q.create_date  # datetime object UTC naive
        if create_utc:
            create_local = pytz.utc.localize(create_utc).astimezone(tz)
            hour_local = create_local.hour + create_local.minute / 60.0
            # Kiểm tra window tại thời điểm nhận
            weekday = create_local.weekday()  # 6 = Sunday
            is_sunday = weekday == 6
            if config.webhook_publish_time_restrict and not is_sunday:
                in_win = config.webhook_publish_time_from <= hour_local < config.webhook_publish_time_to
            elif config.webhook_publish_time_restrict and is_sunday:
                in_win = False
            else:
                in_win = True
            time_str = create_local.strftime('%d/%m %H:%M:%S')
            day_name = ['T2','T3','T4','T5','T6','T7','CN'][weekday]
            time_str = f'{time_str} ({day_name})'
        else:
            time_str = '?'
            hour_local = 0
            in_win = '?'

        # processed_at
        proc_local = ''
        if q.processed_at:
            p = pytz.utc.localize(q.processed_at).astimezone(tz)
            proc_local = p.strftime('%H:%M:%S')

        window_label = '✓ TRONG' if in_win is True else ('✗ NGOÀI' if in_win is False else '?')
        err_short = (q.error_msg or '')[:60].replace('\n', ' ')
        print(f'  {so_name:<10} {time_str:<22} {hour_local:>6.2f} {window_label:>14} {q.state:<12} {q.attempts:>8}  {err_short}')

# ── Tổng hợp tất cả queue gần đây ───────────────────────────────────────────
print(f'\n[TẤT CẢ QUEUE 7 NGÀY GẦN ĐÂY — ngoài khung giờ nhưng đã xử lý]')
from datetime import timedelta
cutoff = datetime.utcnow() - timedelta(days=7)
all_queues = env['amis.webhook.queue'].sudo().search([
    ('create_date', '>=', cutoff.strftime('%Y-%m-%d %H:%M:%S')),
    ('state', 'in', ('done', 'error')),
], order='create_date asc', limit=200)

outside_processed = []
for q in all_queues:
    if not q.create_date:
        continue
    create_local = pytz.utc.localize(q.create_date).astimezone(tz)
    hour_local = create_local.hour + create_local.minute / 60.0
    weekday = create_local.weekday()
    is_sunday = weekday == 6
    if config.webhook_publish_time_restrict:
        in_win = (not is_sunday) and (config.webhook_publish_time_from <= hour_local < config.webhook_publish_time_to)
        if not in_win:
            outside_processed.append((q, create_local, hour_local, weekday))

if outside_processed:
    print(f'  {"SO":<10} {"Nhận lúc":<22} {"Giờ":>6} {"Ngày":>4}  {"State":<10}  Lỗi')
    print(f'  {"─" * 90}')
    for q, cl, hl, wd in outside_processed:
        day_name = ['T2','T3','T4','T5','T6','T7','CN'][wd]
        so_name = q.sale_order_id.name if q.sale_order_id else (q.order_ref or '?')
        err_short = (q.error_msg or '')[:50].replace('\n', ' ')
        print(f'  {so_name:<10} {cl.strftime("%d/%m %H:%M:%S"):<22} {hl:>6.2f} {day_name:>4}  {q.state:<10}  {err_short}')
    print(f'\n  → Có {len(outside_processed)} đơn được xử lý ngoài khung giờ')
    print(f'  Nguyên nhân có thể:')
    print(f'    1. Feature khung giờ chưa deploy khi đơn đó được tạo')
    print(f'    2. Đơn là "error" bị retry khi vào giờ sáng hôm sau (đúng), nhưng inv_date cũ → InvalidInvoiceDate')
else:
    print(f'  Không có đơn nào bị xử lý ngoài khung giờ trong 7 ngày qua.')

# ── Kiểm tra inv_date của các draft/submitted ─────────────────────────────────
print(f'\n[HĐĐT có inv_date không phải hôm nay → nguy cơ InvalidInvoiceDate]')
today_local = now_local.date()
stale_invoices = env['meinvoice.invoice'].sudo().search([
    ('state', '=', 'draft'),
    ('inv_date', '!=', today_local.strftime('%Y-%m-%d')),
], limit=50)
if stale_invoices:
    print(f'  {"ID":>6}  {"SO":<10}  {"inv_date":<12}  {"series":<12}  {"total":>12}')
    print(f'  {"─" * 60}')
    for inv in stale_invoices:
        so_name = inv.sale_order_id.name if inv.sale_order_id else '?'
        print(f'  {inv.id:>6}  {so_name:<10}  {str(inv.inv_date):<12}  {inv.inv_series:<12}  {inv.total_amount_oc:>12,.0f}')
    print(f'\n  → {len(stale_invoices)} HĐĐT nháp có inv_date ≠ hôm nay ({today_local})')
    print(f'     Khi webhook auto-publish gửi các đơn này sẽ bị lỗi InvalidInvoiceDate')
    print(f'     FIX: action_publish() cần tự update inv_date = ngày gửi thật')
else:
    print(f'  Tất cả HĐĐT nháp đều có inv_date = hôm nay hoặc không có nháp nào.')

print(f'\n{"=" * 75}\nXONG\n{"=" * 75}')
