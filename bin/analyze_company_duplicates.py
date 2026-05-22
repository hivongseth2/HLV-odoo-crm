# -*- coding: utf-8 -*-
"""
analyze_company_duplicates.py
==============================
Phân tích duplicate companies (is_company=True) - dùng SQL batch để nhanh.

Cách chạy:
    odoo-bin shell -c <odoo.conf> --no-http < bin/analyze_company_duplicates.py
"""

from collections import defaultdict

SEP  = "=" * 90

def section(title):
    print(f"\n{SEP}\n  {title}\n{SEP}")

def batch_counts(cr, table, field, ids):
    """Trả về dict {partner_id: count} cho toàn bộ ids trong 1 SQL query."""
    if not ids:
        return {}
    cr.execute(
        f"SELECT {field}, COUNT(*) FROM {table} WHERE {field} = ANY(%s) GROUP BY {field}",
        (list(ids),)
    )
    return {row[0]: row[1] for row in cr.fetchall()}

# ─────────────────────────────────────────────────────────────────────────────
# Load toàn bộ companies + đếm PO/SO/child bằng SQL batch (1 lần duy nhất)
# ─────────────────────────────────────────────────────────────────────────────
print("\n  Đang load companies...")
all_companies = env['res.partner'].sudo().search([
    ('is_company', '=', True),
    ('active', 'in', [True, False]),
], order='name asc')

all_ids = set(all_companies.ids)
cr = env.cr

print(f"  Tổng companies: {len(all_ids)}. Đang đếm PO/SO/child...")
po_counts  = batch_counts(cr, 'purchase_order', 'partner_id', all_ids)
so_counts  = batch_counts(cr, 'sale_order',     'partner_id', all_ids)
child_counts = batch_counts(cr, 'res_partner',  'parent_id',  all_ids)
print("  Xong. Bắt đầu phân tích...\n")

# ─────────────────────────────────────────────────────────────────────────────
# A. FULL LOGIN của các create_uid tạo company
# ─────────────────────────────────────────────────────────────────────────────
section("A. FULL LOGIN - Ai đang tạo company (is_company=True)?")

uid_groups = defaultdict(list)
for p in all_companies:
    uid_key = (p.create_uid.id, p.create_uid.login or '__unknown__')
    uid_groups[uid_key].append(p)

print(f"\n  {'ID':>5}  {'LOGIN (FULL)':35}  {'SỐ CÔNG TY':>12}  GHI CHÚ")
print(f"  {'-'*5}  {'-'*35}  {'-'*12}  {'-'*30}")
for (uid_id, login), partners in sorted(uid_groups.items(), key=lambda x: -len(x[1])):
    is_api = uid_id not in (1, 2) and len(partners) > 10
    note = '← nghi ngờ API user' if is_api else ''
    print(f"  {uid_id:>5}  {login[:35]:35}  {len(partners):>12}  {note}")

# ─────────────────────────────────────────────────────────────────────────────
# B. TOP DUPLICATE COMPANIES (is_company=True) - hiển thị đầy đủ
# ─────────────────────────────────────────────────────────────────────────────
section("B. TOP 20 NHÓM DUPLICATE COMPANIES (is_company=True, cùng tên)")

name_groups = defaultdict(list)
for p in all_companies:
    key = (p.name or '').strip().upper()
    name_groups[key].append(p)

duplicates = {k: v for k, v in name_groups.items() if len(v) > 1}
print(f"\n  Tổng công ty: {len(all_companies)}")
print(f"  Tên bị dup  : {len(duplicates)}\n")

for name, partners in sorted(duplicates.items(), key=lambda x: -len(x[1]))[:20]:
    total_po = sum(po_counts.get(p.id, 0) for p in partners)
    total_so = sum(so_counts.get(p.id, 0) for p in partners)
    ids_str = ', '.join(str(p.id) for p in partners)
    print(f"  [{len(partners)}x] {name[:70]}")
    print(f"       IDs=[{ids_str}]  total PO={total_po}  total SO={total_so}")
    print()

# ─────────────────────────────────────────────────────────────────────────────
# C. MILWAUKEE TOOL - TÌM CHÍNH XÁC
# ─────────────────────────────────────────────────────────────────────────────
section("C. MILWAUKEE TOOL - Chi tiết các CÔNG TY (is_company=True)")

mw_companies = env['res.partner'].sudo().search([
    ('name', 'ilike', 'milwaukee'),
    ('is_company', '=', True),
    ('active', 'in', [True, False]),
], order='id asc')

print(f"\n  Tổng công ty có 'milwaukee': {len(mw_companies)}\n")

for p in mw_companies:
    po_count   = po_counts.get(p.id, 0)
    so_count   = so_counts.get(p.id, 0)
    child_count = child_counts.get(p.id, 0)

    print(f"  ┌─ id={p.id}  active={p.active}")
    print(f"  │  name       : {p.name}")
    print(f"  │  vat        : {p.vat or '(trống)'}")
    print(f"  │  phone      : {p.phone or '(trống)'}")
    print(f"  │  ref        : {p.ref or '(trống)'}")
    print(f"  │  create_uid : {p.create_uid.login if p.create_uid else '?'} (id={p.create_uid.id if p.create_uid else '?'})")
    print(f"  │  create_date: {p.create_date}")
    print(f"  │  PO count   : {po_count}")
    print(f"  │  SO count   : {so_count}")
    print(f"  │  child count: {child_count}  (số địa chỉ/liên hệ con)")

    if po_count:
        pos = env['purchase.order'].sudo().search([('partner_id', '=', p.id)], limit=5, order='id desc')
        for po in pos:
            print(f"  │    PO: {po.name}  state={po.state}  date={str(po.date_order)[:10]}")

    print(f"  └{'─'*70}\n")

# ─────────────────────────────────────────────────────────────────────────────
# D. CHẨN ĐOÁN: Tại sao bị duplicate? Nhìn vào thời gian tạo
# ─────────────────────────────────────────────────────────────────────────────
section("D. CHẨN ĐOÁN - Nhóm dup có PO/SO > 0 (ảnh hưởng thực tế)")

print(f"\n  {'TÊN':55}  {'ID':>7}  {'PO':>4}  {'SO':>4}  {'CREATE_UID':30}  {'CREATE_DATE'}")
print(f"  {'-'*55}  {'-'*7}  {'-'*4}  {'-'*4}  {'-'*30}  {'-'*20}")

impacted_groups = []
for name, partners in sorted(duplicates.items(), key=lambda x: x[0]):
    group_data = [(p, po_counts.get(p.id, 0), so_counts.get(p.id, 0)) for p in partners]

    if any(pc > 0 or sc > 0 for _, pc, sc in group_data):
        impacted_groups.append((name, group_data))
        for p, pc, sc in group_data:
            login = (p.create_uid.login or '?')[:30]
            date_str = str(p.create_date)[:19] if p.create_date else 'N/A'
            marker = '  ← CÓ DỮ LIỆU' if (pc > 0 or sc > 0) else '  ← rỗng (có thể xóa)'
            print(f"  {name[:55]:55}  {p.id:>7}  {pc:>4}  {sc:>4}  {login:30}  {date_str}{marker}")
        print()

print(f"\n  Tổng số nhóm dup có ảnh hưởng thực tế: {len(impacted_groups)}")

# ─────────────────────────────────────────────────────────────────────────────
# E. GỢI Ý HÀNH ĐỘNG: nhóm dup nào có thể deactivate an toàn
# ─────────────────────────────────────────────────────────────────────────────
section("E. GỢI Ý - IDs có thể deactivate an toàn (rỗng: PO=0, SO=0, child=0)")

safe_to_deactivate = []
for name, partners in duplicates.items():
    for p in partners:
        po_c    = po_counts.get(p.id, 0)
        so_c    = so_counts.get(p.id, 0)
        child_c = child_counts.get(p.id, 0)
        if po_c == 0 and so_c == 0 and child_c == 0:
            siblings = [sp for sp in partners if sp.id != p.id]
            sibling_has_data = any(
                po_counts.get(sp.id, 0) > 0 or so_counts.get(sp.id, 0) > 0
                for sp in siblings
            )
            if sibling_has_data or len(siblings) >= 1:
                safe_to_deactivate.append((p, name))

print(f"\n  Tổng IDs có thể deactivate an toàn: {len(safe_to_deactivate)}\n")

# Gom theo tên
by_name = defaultdict(list)
for p, name in safe_to_deactivate:
    by_name[name].append(p)

for name, partners in list(by_name.items())[:30]:
    ids_str = ', '.join(str(p.id) for p in partners)
    logins = ', '.join((p.create_uid.login or '?') for p in partners)
    print(f"  [{len(partners)}x deactivate] {name[:60]}")
    print(f"       IDs=[{ids_str}]  tạo bởi: {logins}")

if len(by_name) > 30:
    print(f"\n  ... và {len(by_name)-30} nhóm khác")

# In ra lệnh deactivate (DRY RUN - chưa chạy thực)
all_safe_ids = [p.id for p, _ in safe_to_deactivate]
print(f"\n  ── DRY RUN - để thực sự deactivate, bỏ comment dòng bên dưới ──")
print(f"  # Tổng {len(all_safe_ids)} records")
print(f"  # SAFE_IDS = {all_safe_ids[:50]}{'...' if len(all_safe_ids)>50 else ''}")
print(f"  # env['res.partner'].sudo().browse(SAFE_IDS).write({{'active': False}})")
print(f"  # env.cr.commit()")

print(f"\n{SEP}")
print("  XONG.")
print(SEP)
