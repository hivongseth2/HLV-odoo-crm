#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Debug script v2: Kiểm tra cột "Đã Giao Trong Ngày" sau fix.

Chạy bằng Odoo shell:
  python odoo-bin shell -c odoo.conf -d <database_name> < debug_delivered_today.py
"""

from odoo.fields import Date as OdooDate
from datetime import datetime
import pytz

user_tz = pytz.timezone(env.context.get('tz') or env.user.tz or 'Asia/Ho_Chi_Minh')
today_date = OdooDate.context_today(env['sale.order'])
now_utc = datetime.now(pytz.utc)
now_local = now_utc.astimezone(user_tz)

print("=" * 80)
print(f"DEBUG v2: Đã Giao Trong Ngày - {now_local.strftime('%Y-%m-%d %H:%M:%S %Z')}")
print(f"UTC now: {now_utc.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"today_date (context_today): {today_date}")
print(f"user_tz: {user_tz}")
print("=" * 80)

# 1. Tìm picking OUT done hôm nay (so sánh timezone-aware)
print("\n--- 1. PICKING OUTGOING DONE HÔM NAY (TZ-AWARE) ---")
all_done_out = env['stock.picking'].sudo().search([
    ('picking_type_code', '=', 'outgoing'),
    ('state', '=', 'done'),
    ('return_id', '=', False),
])
today_done = []
for p in all_done_out:
    if p.date_done:
        local_date = p.date_done.replace(tzinfo=pytz.utc).astimezone(user_tz).date()
        if local_date == today_date:
            today_done.append((p, local_date))

print(f"Tổng picking OUT done: {len(all_done_out)}")
print(f"Picking OUT done HÔM NAY (local {today_date}): {len(today_done)}")
for p, ld in today_done[:20]:
    utc_dt = p.date_done
    local_dt = utc_dt.replace(tzinfo=pytz.utc).astimezone(user_tz)
    so_name = p.sale_id.name if p.sale_id else '(no SO)'
    print(f"  {p.name} | SO: {so_name} | date_done_utc={utc_dt} | date_done_local={local_dt.strftime('%Y-%m-%d %H:%M:%S')} | local_date={ld}")

# 2. Gọi get_dashboard_data
print("\n--- 2. get_dashboard_data filter='delivered_today' (default, KHÔNG show_completed) ---")
try:
    service = env['hlv.delivery.planner.service'].sudo()
    result = service.get_dashboard_data(
        filter_packing_status='delivered_today',
        limit=20,
        offset=0,
    )
    orders = result.get('orders', [])
    print(f"Kết quả: {len(orders)} đơn")
    for o in orders[:10]:
        print(f"  {o.get('name')} | effective_packing={o.get('effective_packing')} | real_delivery_status={o.get('real_delivery_status')} | has_delivered_today={o.get('has_delivered_today')}")
    if not orders:
        print("  (trống — vẫn bị lỗi!)")
except Exception as e:
    print(f"Lỗi: {e}")
    import traceback; traceback.print_exc()

# 3. Gọi get_dashboard_data không filter (xem cột delivered_today trong KPI)
print("\n--- 3. get_dashboard_data không filter (kiểm tra KPI counts) ---")
try:
    service = env['hlv.delivery.planner.service'].sudo()
    result = service.get_dashboard_data(
        limit=250,
        offset=0,
    )
    orders = result.get('orders', [])
    kpi = result.get('kpi', {})
    print(f"Tổng đơn trả về: {len(orders)}")
    print(f"KPI: {kpi}")
    # Tìm đơn có has_delivered_today
    dt_orders = [o for o in orders if o.get('has_delivered_today')]
    print(f"Đơn có has_delivered_today=True: {len(dt_orders)}")
    for o in dt_orders[:5]:
        print(f"  {o.get('name')} | effective_packing={o.get('effective_packing')} | real_delivery_status={o.get('real_delivery_status')}")
except Exception as e:
    print(f"Lỗi: {e}")
    import traceback; traceback.print_exc()

print("\n" + "=" * 80)
print("DEBUG v2 XONG")
print("=" * 80)
