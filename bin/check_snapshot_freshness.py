# -*- coding: utf-8 -*-
"""
check_snapshot_freshness.py
============================
Kiểm tra vì sao hlv.delivery.planner.snapshot luôn bị coi là "stale_date"
(snapshot_date != hôm nay) trong lần profiling trước (589/589 records) — khiến
fast-path dashboard KHÔNG BAO GIỜ được dùng, mọi lần "xóa search" đều rơi vào
tính live cho toàn bộ tập kết quả.

Giả thuyết: cron "Delivery Planner: Refresh Dirty Snapshots" chạy bởi user
base.user_root — nếu user này có tz khác giờ Việt Nam (VD UTC), thì
fields.Date.context_today() bên trong cron sẽ tính "hôm nay" lệch 1 ngày so
với "hôm nay" thật của user thường (Asia/Ho_Chi_Minh) trong phần lớn giờ hành
chính VN — khiến snapshot_date ghi vào luôn bị coi là "cũ" ngay khi user thật
đọc lại.

CHỈ ĐỌC — không write/create/unlink gì.

Chạy bằng lệnh (trên Odoo.sh shell):
    python odoo-bin shell -d <TEN_DATABASE> < bin/check_snapshot_freshness.py
"""

from datetime import datetime, timezone
from odoo.fields import Date as OdooDate

cr = env.cr

SEP = "=" * 90
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

# ─────────────────────────────────────────────
# 1. Giờ hệ thống & context_today() theo các user khác nhau
# ─────────────────────────────────────────────
section("1. So sánh 'hôm nay' theo các user/tz khác nhau")

now_utc = datetime.now(timezone.utc)
print(f"  UTC now                         : {now_utc.strftime('%Y-%m-%d %H:%M:%S %Z')}")

root_user = env.ref('base.user_root')
print(f"  base.user_root.tz                : {root_user.tz!r}")
today_as_root = OdooDate.context_today(root_user)
print(f"  context_today() theo user_root    : {today_as_root}")

today_as_vn = OdooDate.context_today(env.user.with_context(tz='Asia/Ho_Chi_Minh'))
print(f"  context_today() theo tz VN cứng   : {today_as_vn}")

print(f"  env.user hiện tại (chạy script)   : {env.user.name!r} tz={env.user.tz!r}")
today_as_me = OdooDate.context_today(env.user)
print(f"  context_today() theo env.user     : {today_as_me}")

if today_as_root != today_as_vn:
    print("\n  !!! LỆCH NGÀY: user_root và giờ VN đang tính 'hôm nay' KHÁC NHAU.")
    print("      => Đúng như nghi ngờ: cron chạy bằng user_root sẽ ghi snapshot_date SAI")
    print("         so với 'hôm nay' thật của user Việt Nam trong phần lớn giờ hành chính.")
else:
    print("\n  OK: user_root và giờ VN đang trùng 'hôm nay' TẠI THỜI ĐIỂM NÀY (có thể lệch")
    print("      vào giờ khác trong ngày nếu tz user_root không phải Asia/Ho_Chi_Minh).")

# ─────────────────────────────────────────────
# 2. Cron có đang chạy đúng lịch không?
# ─────────────────────────────────────────────
section("2. Trạng thái cron 'Delivery Planner: Refresh Dirty Snapshots'")
cron = env.ref('hlv_sale_delivery_planning.ir_cron_hlv_delivery_planner_snapshot_refresh', raise_if_not_found=False)
if not cron:
    print("  !!! KHÔNG TÌM THẤY cron record — external id có thể đã đổi hoặc module chưa update.")
else:
    print(f"  active       : {cron.active}")
    print(f"  interval     : {cron.interval_number} {cron.interval_type}")
    print(f"  lastcall     : {cron.lastcall}")
    print(f"  nextcall     : {cron.nextcall}")
    print(f"  user_id      : {cron.user_id.name!r} (tz={cron.user_id.tz!r})")

# ─────────────────────────────────────────────
# 3. Phân bố snapshot_date hiện tại trên toàn bộ snapshot đang "sale"/"done"
# ─────────────────────────────────────────────
section("3. Phân bố snapshot_date + dirty trên toàn bộ snapshot")
cr.execute("""
    SELECT snapshot_date, dirty, count(*)
      FROM hlv_delivery_planner_snapshot
     GROUP BY snapshot_date, dirty
     ORDER BY snapshot_date DESC NULLS LAST, dirty
     LIMIT 20
""")
rows = cr.fetchall()
print(f"  {'snapshot_date':>14}  {'dirty':>6}  {'count':>8}")
for snap_date, dirty, cnt in rows:
    print(f"  {str(snap_date):>14}  {str(dirty):>6}  {cnt:>8}")

cr.execute("SELECT count(*) FROM hlv_delivery_planner_snapshot")
total_snap = cr.fetchone()[0]
print(f"\n  Tổng snapshot: {total_snap}")

# ─────────────────────────────────────────────
# 4. logic_version hiện có so với SNAPSHOT_LOGIC_VERSION trong code
# ─────────────────────────────────────────────
section("4. logic_version snapshot so với code hiện tại")
from odoo.addons.hlv_sale_delivery_planning.models.delivery_planner_snapshot import SNAPSHOT_LOGIC_VERSION
print(f"  SNAPSHOT_LOGIC_VERSION trong code: {SNAPSHOT_LOGIC_VERSION!r}")
cr.execute("SELECT logic_version, count(*) FROM hlv_delivery_planner_snapshot GROUP BY logic_version")
for ver, cnt in cr.fetchall():
    flag = "  <-- KHỚP code" if ver == SNAPSHOT_LOGIC_VERSION else "  <-- CŨ, không khớp"
    print(f"  {ver!r:>30}: {cnt}{flag}")

section("XONG")
print("  Nếu mục 1 báo LỆCH NGÀY và mục 3 cho thấy phần lớn snapshot có snapshot_date")
print("  != ngày VN hôm nay (dù dirty=False) -> xác nhận đúng bug: fast-path luôn bị")
print("  vô hiệu hóa do lệch timezone giữa cron (user_root) và user thật.")
