# -*- coding: utf-8 -*-
"""
debug_milwaukee_full.py
========================
Dump TOÀN BỘ dữ liệu liên quan đến Milwaukee để hiểu cấu trúc data.

Cách chạy:
    odoo-bin shell -c <odoo.conf> --no-http < bin/debug_milwaukee_full.py
"""

SEP  = "=" * 100
SEP2 = "-" * 100

def section(title):
    print(f"\n{SEP}\n  {title}\n{SEP}")

def subsection(title):
    print(f"\n  {SEP2}\n  {title}\n  {SEP2}")

# ─────────────────────────────────────────────────────────────────────────────
# 1. TẤT CẢ PARTNER có chữ "milwaukee" (active + inactive)
# ─────────────────────────────────────────────────────────────────────────────
TARGET_NAME = 'CÔNG TY TNHH MILWAUKEE TOOL (VIỆT NAM)'

section(f"1. TẤT CẢ PARTNER tên = '{TARGET_NAME}' (active + inactive)")

mw_all = env['res.partner'].sudo().search([
    ('name', '=', TARGET_NAME),
    ('active', 'in', [True, False]),
], order='id asc')

print(f"\n  Tổng: {len(mw_all)} records\n")
print(f"  {'ID':>7}  {'ACTIVE':>6}  {'IS_CO':>5}  {'TYPE':12}  {'PARENT_ID':>9}  {'NAME'}")
print(f"  {'-'*7}  {'-'*6}  {'-'*5}  {'-'*12}  {'-'*9}  {'-'*60}")
for p in mw_all:
    parent_str = str(p.parent_id.id) if p.parent_id else '-'
    print(f"  {p.id:>7}  {str(p.active):>6}  {str(p.is_company):>5}  {(p.type or 'contact'):12}  {parent_str:>9}  {p.name}")

# ─────────────────────────────────────────────────────────────────────────────
# 2. CHI TIẾT TỪNG RECORD - tất cả fields quan trọng
# ─────────────────────────────────────────────────────────────────────────────
section("2. CHI TIẾT TỪNG RECORD")

for p in mw_all:
    print(f"\n  ┌{'─'*98}")
    print(f"  │ ID={p.id}  active={p.active}  is_company={p.is_company}  type={p.type or 'contact'}")
    print(f"  │ name        : {p.name}")
    print(f"  │ complete_name: {p.complete_name}")
    print(f"  │ display_name : {p.display_name}")
    print(f"  │ parent_id   : {p.parent_id.id if p.parent_id else '-'}  ({p.parent_id.name if p.parent_id else 'none'})")
    print(f"  │ commercial_partner_id: {p.commercial_partner_id.id}  ({p.commercial_partner_id.name})")
    print(f"  │ ref         : {p.ref or '(trống)'}")
    print(f"  │ vat         : {p.vat or '(trống)'}")
    print(f"  │ phone       : {p.phone or '(trống)'}")
    print(f"  │ mobile      : {p.mobile or '(trống)'}")
    print(f"  │ email       : {p.email or '(trống)'}")
    print(f"  │ street      : {p.street or '(trống)'}")
    print(f"  │ city        : {p.city or '(trống)'}")
    print(f"  │ country     : {p.country_id.name if p.country_id else '(trống)'}")
    print(f"  │ lang        : {p.lang or '(trống)'}")
    print(f"  │ customer_rank: {p.customer_rank}")
    print(f"  │ supplier_rank: {p.supplier_rank}")
    print(f"  │ create_uid  : {p.create_uid.login if p.create_uid else '?'}  (id={p.create_uid.id if p.create_uid else '?'})")
    print(f"  │ create_date : {p.create_date}")
    print(f"  │ write_uid   : {p.write_uid.login if p.write_uid else '?'}")
    print(f"  │ write_date  : {p.write_date}")
    print(f"  └{'─'*98}")

# ─────────────────────────────────────────────────────────────────────────────
# 3. CÁC PARTNER CON (child_ids) của từng company Milwaukee
# ─────────────────────────────────────────────────────────────────────────────
section("3. CONTACTS CON / ĐỊA CHỈ CON của các company Milwaukee")

mw_companies = [p for p in mw_all if p.is_company]
print(f"\n  Có {len(mw_companies)} company Milwaukee\n")

for company in mw_companies:
    children = env['res.partner'].sudo().search([
        ('parent_id', '=', company.id),
        ('active', 'in', [True, False]),
    ], order='id asc')
    print(f"\n  Company id={company.id}  name='{company.name}'  active={company.active}")
    print(f"  Có {len(children)} record con:\n")
    print(f"    {'ID':>7}  {'ACTIVE':>6}  {'TYPE':15}  {'NAME':50}  {'PHONE':15}")
    print(f"    {'-'*7}  {'-'*6}  {'-'*15}  {'-'*50}  {'-'*15}")
    for c in children:
        print(f"    {c.id:>7}  {str(c.active):>6}  {(c.type or 'contact'):15}  {(c.name or ''):50}  {c.phone or ''}")

# ─────────────────────────────────────────────────────────────────────────────
# 4. TẤT CẢ PURCHASE ORDERS liên quan Milwaukee
# ─────────────────────────────────────────────────────────────────────────────
section("4. PURCHASE ORDERS liên quan Milwaukee")

all_mw_ids = mw_all.ids
if all_mw_ids:
    env.cr.execute("""
        SELECT po.id, po.name, po.state, po.date_order,
               p.id as partner_id, p.name as partner_name, p.is_company, p.type, p.parent_id
        FROM purchase_order po
        JOIN res_partner p ON po.partner_id = p.id
        WHERE po.partner_id = ANY(%s)
        ORDER BY po.date_order DESC
    """, (all_mw_ids,))
    rows = env.cr.fetchall()
    print(f"\n  Tổng PO liên quan: {len(rows)}\n")
    print(f"  {'PO_ID':>7}  {'PO_NAME':15}  {'STATE':10}  {'DATE':12}  {'PARTNER_ID':>10}  {'IS_CO':>5}  {'TYPE':12}  {'PARENT':>7}  PARTNER_NAME")
    print(f"  {'-'*7}  {'-'*15}  {'-'*10}  {'-'*12}  {'-'*10}  {'-'*5}  {'-'*12}  {'-'*7}  {'-'*50}")
    for row in rows:
        po_id, po_name, state, date_order, pid, pname, is_co, ptype, parent_id = row
        date_str = str(date_order)[:10] if date_order else '-'
        parent_str = str(parent_id) if parent_id else '-'
        print(f"  {po_id:>7}  {(po_name or ''):15}  {(state or ''):10}  {date_str:12}  {pid:>10}  {str(is_co):>5}  {(ptype or 'contact'):12}  {parent_str:>7}  {pname or ''}")
else:
    print("\n  Không có ID Milwaukee nào.")

# ─────────────────────────────────────────────────────────────────────────────
# 5. TẤT CẢ SALE ORDERS liên quan Milwaukee
# ─────────────────────────────────────────────────────────────────────────────
section("5. SALE ORDERS liên quan Milwaukee")

if all_mw_ids:
    env.cr.execute("""
        SELECT so.id, so.name, so.state, so.date_order,
               p.id as partner_id, p.name as partner_name, p.is_company, p.type, p.parent_id
        FROM sale_order so
        JOIN res_partner p ON so.partner_id = p.id
        WHERE so.partner_id = ANY(%s)
        ORDER BY so.date_order DESC
        LIMIT 30
    """, (all_mw_ids,))
    rows = env.cr.fetchall()
    print(f"\n  (Hiển thị tối đa 30 SO gần nhất)\n")
    print(f"  {'SO_ID':>7}  {'SO_NAME':15}  {'STATE':10}  {'DATE':12}  {'PARTNER_ID':>10}  {'IS_CO':>5}  {'TYPE':12}  {'PARENT':>7}  PARTNER_NAME")
    print(f"  {'-'*7}  {'-'*15}  {'-'*10}  {'-'*12}  {'-'*10}  {'-'*5}  {'-'*12}  {'-'*7}  {'-'*50}")
    for row in rows:
        so_id, so_name, state, date_order, pid, pname, is_co, ptype, parent_id = row
        date_str = str(date_order)[:10] if date_order else '-'
        parent_str = str(parent_id) if parent_id else '-'
        print(f"  {so_id:>7}  {(so_name or ''):15}  {(state or ''):10}  {date_str:12}  {pid:>10}  {str(is_co):>5}  {(ptype or 'contact'):12}  {parent_str:>7}  {pname or ''}")

# ─────────────────────────────────────────────────────────────────────────────
# 6. CHATTER MESSAGES trên từng company Milwaukee (5 message gần nhất)
# ─────────────────────────────────────────────────────────────────────────────
section(f"6. CHATTER MESSAGES (5 gần nhất) trên các company '{TARGET_NAME}'")

for company in mw_companies:
    msgs = env['mail.message'].sudo().search([
        ('model', '=', 'res.partner'),
        ('res_id', '=', company.id),
    ], order='id desc', limit=5)
    print(f"\n  Company id={company.id}  '{company.name}'  ({len(msgs)} msgs)")
    for m in msgs:
        body_short = (m.body or '').replace('\n', ' ')[:80]
        print(f"    [{m.id}] {str(m.date)[:19]}  author={m.author_id.name if m.author_id else '?'}  subtype={m.subtype_id.name if m.subtype_id else '-'}")
        print(f"         body: {body_short}")

# ─────────────────────────────────────────────────────────────────────────────
# 7. TÓM TẮT: Đây là dữ liệu gì?
# ─────────────────────────────────────────────────────────────────────────────
section(f"7. TÓM TẮT PHÂN TÍCH  — '{TARGET_NAME}'")

print(f"""
  Số partner Milwaukee tìm được  : {len(mw_all)}
    - is_company=True             : {len([p for p in mw_all if p.is_company])}
    - is_company=False (contact)  : {len([p for p in mw_all if not p.is_company])}
    - active=True                 : {len([p for p in mw_all if p.active])}
    - active=False (archived)     : {len([p for p in mw_all if not p.active])}
    - type=delivery               : {len([p for p in mw_all if p.type == 'delivery'])}
    - có parent_id                : {len([p for p in mw_all if p.parent_id])}
""")

print("  Done.")
