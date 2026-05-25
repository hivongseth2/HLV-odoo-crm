# -*- coding: utf-8 -*-
"""
check_recent_archived.py
========================
Kiểm tra các res.partner bị archive trong 24h gần nhất.
Nếu muốn RESTORE: đổi RESTORE = True
"""

from datetime import datetime, timedelta

RESTORE = False   # ← đổi True để restore lại

SEP = "=" * 90
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

cr = env.cr
since = datetime.now() - timedelta(hours=24)

# Tìm partners bị archive gần đây (active=False, write_date trong 24h)
cr.execute("""
    SELECT id, name, write_date, ref, company_registry, vat, is_company, parent_id
    FROM res_partner
    WHERE active = False
      AND write_date >= %s
    ORDER BY write_date DESC
""", (since,))
rows = cr.fetchall()

section(f"Partners bị archive trong 24h qua: {len(rows)}")
print(f"\n  {'ID':>7}  {'IS_CO':>5}  {'PAR':>7}  {'REF':>10}  {'WRITE_DATE':>20}  NAME")
print(f"  {'-'*7}  {'-'*5}  {'-'*7}  {'-'*10}  {'-'*20}  {'-'*50}")
for pid, name, wdate, ref, creg, vat, is_co, par in rows:
    print(f"  {pid:>7}  {str(is_co):>5}  {str(par or ''):>7}  {str(ref or ''):>10}  {str(wdate)[:19]:>20}  {str(name or '')[:50]}")

if not rows:
    print("\n  Không có gì bị archive gần đây.")
elif RESTORE:
    section(f"RESTORE {len(rows)} partners ...")
    ids = tuple(r[0] for r in rows)
    cr.execute("UPDATE res_partner SET active = True WHERE id IN %s", (ids,))
    env.cr.commit()
    print(f"  Đã restore {len(ids)} partners.")
else:
    section("DRY — Đổi RESTORE = True để phục hồi")
    print(f"\n  Sẽ restore {len(rows)} records (set active=True)")
    print("\n  LƯU Ý: Đơn hàng đã được chuyển sang master_id — cần kiểm tra thủ công")
    print("         nếu muốn chuyển đơn về lại dup thì phải viết script riêng.")

print("\n  Done.")
