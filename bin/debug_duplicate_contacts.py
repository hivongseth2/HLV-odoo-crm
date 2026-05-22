# -*- coding: utf-8 -*-
"""
debug_duplicate_contacts.py
============================
Phân tích duplicate contacts và xem 20 đơn mua hàng gần nhất
được tạo từ contact nào.

Cách chạy:
    odoo-bin shell -c <odoo.conf> --no-http < bin/debug_duplicate_contacts.py

Nội dung kiểm tra:
  A) Top duplicate contacts (cùng tên hoặc cùng email/phone)
  B) Chi tiết các nhóm duplicate của "MILWAUKEE TOOL" (ví dụ từ screenshot)
  C) 20 đơn mua hàng (purchase.order) gần nhất và contact nguồn của chúng
  D) Thống kê: bao nhiêu PO dùng contact bị dup, audit trail (create_uid)
"""

import sys
from collections import defaultdict

SEP  = "=" * 80
SEP2 = "-" * 80

def section(title):
    print(f"\n{SEP}\n  {title}\n{SEP}")

def sub(title):
    print(f"\n  {SEP2}\n  {title}\n  {SEP2}")

# ─────────────────────────────────────────────────────────────────────────────
# A. TÌM DUPLICATE CONTACTS THEO TÊN
# ─────────────────────────────────────────────────────────────────────────────
section("A. TOP DUPLICATE CONTACTS (cùng name, is_company=True)")

# Lấy tất cả company contacts, group by name
all_companies = env['res.partner'].sudo().search([
    ('is_company', '=', True),
    ('active', 'in', [True, False]),
], order='name asc')

name_groups = defaultdict(list)
for p in all_companies:
    key = (p.name or '').strip().upper()
    name_groups[key].append(p)

duplicates = {k: v for k, v in name_groups.items() if len(v) > 1}
print(f"\n  Tổng số công ty: {len(all_companies)}")
print(f"  Số tên bị duplicate: {len(duplicates)}")

print(f"\n  {'COUNT':>5}  {'TÊN':60}  {'IDs'}")
print(f"  {'-'*5}  {'-'*60}  {'-'*20}")
for name, partners in sorted(duplicates.items(), key=lambda x: -len(x[1]))[:30]:
    ids_str = ', '.join(str(p.id) for p in partners)
    active_flags = ', '.join(str(p.active) for p in partners)
    print(f"  {len(partners):>5}  {name[:60]:<60}  IDs=[{ids_str}] active=[{active_flags}]")

# ─────────────────────────────────────────────────────────────────────────────
# B. CHI TIẾT DUPLICATE: MILWAUKEE TOOL
# ─────────────────────────────────────────────────────────────────────────────
section("B. CHI TIẾT DUPLICATE - MILWAUKEE TOOL")

milwaukee_partners = env['res.partner'].sudo().search([
    ('name', 'ilike', 'milwaukee'),
    ('active', 'in', [True, False]),
], order='id asc')

print(f"\n  Tổng contacts có từ 'milwaukee': {len(milwaukee_partners)}")
print()

for p in milwaukee_partners:
    print(f"  ┌─ id={p.id}  active={p.active}  is_company={p.is_company}")
    print(f"  │  name        : {p.name}")
    print(f"  │  display_name: {p.display_name}")
    print(f"  │  email       : {p.email or '(trống)'}")
    print(f"  │  phone       : {p.phone or '(trống)'}")
    print(f"  │  mobile      : {p.mobile or '(trống)'}")
    print(f"  │  vat         : {p.vat or '(trống)'}")
    print(f"  │  ref         : {p.ref or '(trống)'}")
    print(f"  │  street      : {p.street or '(trống)'}")
    print(f"  │  city        : {p.city or '(trống)'}")
    print(f"  │  country     : {p.country_id.name if p.country_id else '(trống)'}")
    print(f"  │  parent_id   : {p.parent_id.name if p.parent_id else '(trống)'}")
    print(f"  │  type        : {p.type}")
    print(f"  │  create_uid  : {p.create_uid.login if p.create_uid else '?'} (id={p.create_uid.id if p.create_uid else '?'})")
    print(f"  │  create_date : {p.create_date}")
    print(f"  │  write_date  : {p.write_date}")

    # Đếm số PO, SO dùng contact này
    po_count = env['purchase.order'].sudo().search_count([('partner_id', '=', p.id)])
    so_count = env['sale.order'].sudo().search_count([('partner_id', '=', p.id)])
    print(f"  │  PO count    : {po_count}")
    print(f"  │  SO count    : {so_count}")

    # Kiểm tra có phải được tạo qua API không (thường create_uid là admin hoặc 1 user đặc biệt)
    # Lấy source hint từ chatter nếu có
    first_msg = env['mail.message'].sudo().search([
        ('res_id', '=', p.id),
        ('model', '=', 'res.partner'),
    ], order='id asc', limit=1)
    if first_msg:
        print(f"  │  first_msg   : [{first_msg.date}] {first_msg.body[:120] if first_msg.body else '(no body)'}")
    print(f"  └{'─'*70}")
    print()

# ─────────────────────────────────────────────────────────────────────────────
# C. 20 ĐƠN MUA HÀNG GẦN NHẤT
# ─────────────────────────────────────────────────────────────────────────────
section("C. 20 ĐƠN MUA HÀNG (purchase.order) GẦN NHẤT")

recent_pos = env['purchase.order'].sudo().search(
    [], order='id desc', limit=20
)

print(f"\n  {'STT':>3}  {'ID':>6}  {'NAME':20}  {'STATE':10}  {'DATE':20}  "
      f"{'PARTNER_ID':>10}  {'PARTNER_NAME':40}  {'CREATE_UID':15}  {'CREATE_DATE'}")
print(f"  {'-'*3}  {'-'*6}  {'-'*20}  {'-'*10}  {'-'*20}  "
      f"{'-'*10}  {'-'*40}  {'-'*15}  {'-'*20}")

for i, po in enumerate(recent_pos, 1):
    partner = po.partner_id
    create_uid = po.create_uid
    date_str = str(po.date_order)[:19] if po.date_order else 'N/A'
    create_date_str = str(po.create_date)[:19] if po.create_date else 'N/A'
    partner_name = (partner.name or '?')[:40]
    create_login = (create_uid.login if create_uid else '?')[:15]
    print(f"  {i:>3}  {po.id:>6}  {po.name[:20]:20}  {po.state[:10]:10}  {date_str:20}  "
          f"{partner.id:>10}  {partner_name:40}  {create_login:15}  {create_date_str}")

# ─────────────────────────────────────────────────────────────────────────────
# D. AUDIT: PO nào dùng contact trùng lặp?
# ─────────────────────────────────────────────────────────────────────────────
section("D. AUDIT - PO trong 20 đơn gần nhất dùng contact bị DUPLICATE")

dup_partner_ids = set()
for partners in duplicates.values():
    for p in partners:
        dup_partner_ids.add(p.id)

dup_pos = [po for po in recent_pos if po.partner_id.id in dup_partner_ids]
if not dup_pos:
    print("\n  ✅ Không có PO nào trong 20 đơn gần nhất dùng contact bị duplicate.")
else:
    print(f"\n  ⚠️  {len(dup_pos)}/{len(recent_pos)} PO dùng contact bị duplicate:\n")
    for po in dup_pos:
        partner = po.partner_id
        same_name_group = name_groups.get((partner.name or '').strip().upper(), [])
        sibling_ids = [p.id for p in same_name_group if p.id != partner.id]
        print(f"  PO: {po.name} (id={po.id})")
        print(f"    → partner dùng : id={partner.id}  name={partner.name}  active={partner.active}")
        print(f"    → partner trùng: IDs={sibling_ids}")
        print(f"    → create_uid PO: {po.create_uid.login if po.create_uid else '?'}")
        print()

# ─────────────────────────────────────────────────────────────────────────────
# E. THỐNG KÊ: Contact được tạo bởi user/API nào?
# ─────────────────────────────────────────────────────────────────────────────
section("E. THỐNG KÊ - Contacts được tạo bởi create_uid nào? (is_company=True)")

uid_groups = defaultdict(list)
for p in all_companies:
    uid = p.create_uid.login if p.create_uid else '__unknown__'
    uid_groups[uid].append(p)

print(f"\n  {'CREATE_UID (LOGIN)':30}  {'SỐ CONTACT':>12}  GHI CHÚ")
print(f"  {'-'*30}  {'-'*12}  {'-'*30}")
for login, partners in sorted(uid_groups.items(), key=lambda x: -len(x[1])):
    note = '← có thể là API user' if login not in ('__unknown__', 'admin') and len(partners) > 10 else ''
    print(f"  {login[:30]:30}  {len(partners):>12}  {note}")

print(f"\n{SEP}")
print("  XONG. Xem kết quả bên trên để quyết định merge hay xóa duplicate.")
print(SEP)
