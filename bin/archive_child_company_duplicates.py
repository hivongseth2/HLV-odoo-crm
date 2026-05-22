# -*- coding: utf-8 -*-
"""
archive_child_company_duplicates.py
=====================================
Tìm và archive tất cả "công ty con bất thường":
  - is_company=True nhưng có parent_id trỏ tới công ty cha cùng tên
  - Hoặc 2 root company (parent_id=False) cùng tên → archive cái mới hơn

Trước khi archive:
  - Chuyển ref / company_registry → master (nếu master chưa có)
  - Xóa trắng: vat, ref, company_registry, phone, mobile, email, street, city, zip
    của record sắp archive

Bỏ qua (skip) nếu có đơn hàng gần đây (< RECENT_DAYS ngày).

Cách chạy (DRY RUN mặc định):
    odoo-bin shell -c <odoo.conf> --no-http < bin/archive_child_company_duplicates.py

Đổi DRY_RUN = False để thực thi thật.
"""

from datetime import datetime, timedelta

DRY_RUN     = True    # ← đổi False để chạy thật
RECENT_DAYS = 90      # Đơn trong vòng N ngày → skip (không archive)

# ─── helpers ──────────────────────────────────────────────────────────────────
SEP = "=" * 90
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

cutoff_date = datetime.now() - timedelta(days=RECENT_DAYS)
cr = env.cr

def has_recent_orders(partner_id):
    cr.execute("""
        SELECT 1 FROM purchase_order
        WHERE partner_id = %s AND date_order >= %s
        LIMIT 1
    """, (partner_id, cutoff_date))
    if cr.fetchone(): return True
    cr.execute("""
        SELECT 1 FROM sale_order
        WHERE partner_id = %s AND date_order >= %s
        LIMIT 1
    """, (partner_id, cutoff_date))
    return bool(cr.fetchone())

def any_orders(partner_id):
    cr.execute("SELECT COUNT(*) FROM purchase_order WHERE partner_id = %s", (partner_id,))
    if cr.fetchone()[0]: return True
    cr.execute("SELECT COUNT(*) FROM sale_order WHERE partner_id = %s", (partner_id,))
    return bool(cr.fetchone()[0])

def count_orders(partner_id):
    cr.execute("SELECT COUNT(*) FROM purchase_order WHERE partner_id = %s", (partner_id,))
    po = cr.fetchone()[0]
    cr.execute("SELECT COUNT(*) FROM sale_order WHERE partner_id = %s", (partner_id,))
    so = cr.fetchone()[0]
    cr.execute("SELECT COUNT(*) FROM stock_picking WHERE partner_id = %s", (partner_id,))
    pick = cr.fetchone()[0]
    return po, so, pick

# ─── 1. TÌM CÁC CẶP DUPLICATE ────────────────────────────────────────────────
section("1. TÌM CÁC CẶP DUPLICATE COMPANY")

# Loại 1: is_company=True có parent_id cùng tên (chính là anomaly Milwaukee)
cr.execute("""
    SELECT c.id as dup_id, p.id as master_id, c.name
    FROM res_partner c
    JOIN res_partner p ON c.parent_id = p.id
    WHERE c.is_company = True
      AND p.is_company = True
      AND c.active = True
      AND upper(trim(c.name)) = upper(trim(p.name))
    ORDER BY c.name
""")
child_dups = cr.fetchall()   # (dup_id, master_id, name)

# Loại 2: 2 root companies cùng tên (parent_id IS NULL)
cr.execute("""
    SELECT a.id, b.id, a.name
    FROM res_partner a
    JOIN res_partner b ON upper(trim(a.name)) = upper(trim(b.name))
                       AND a.id < b.id
    WHERE a.is_company = True AND b.is_company = True
      AND a.parent_id IS NULL AND b.parent_id IS NULL
      AND a.active = True AND b.active = True
    ORDER BY a.name
""")
root_dups = cr.fetchall()   # (id_older, id_newer, name)

print(f"\n  Loại 1 (con bất thường - is_company+parent_id cùng tên): {len(child_dups)}")
print(f"  Loại 2 (2 root company cùng tên)                        : {len(root_dups)}")

# ─── 2. PHÂN LOẠI: SAFE vs SKIP ───────────────────────────────────────────────
section("2. PHÂN LOẠI")

safe_list  = []   # [(dup_id, master_id, name, reason)]
skip_list  = []   # [(dup_id, master_id, name, reason)]

# -- Loại 1: archive dup (con bất thường), giữ master (cha)
for dup_id, master_id, name in child_dups:
    if has_recent_orders(dup_id):
        po, so, pick = count_orders(dup_id)
        skip_list.append((dup_id, master_id, name,
                          f"dup có đơn gần đây (PO={po} SO={so} pick={pick})"))
    else:
        po, so, pick = count_orders(dup_id)
        safe_list.append((dup_id, master_id, name,
                          f"[loại1-con] PO={po} SO={so} pick={pick}"))

# -- Loại 2: archive cái mới hơn (id lớn hơn = b), giữ cái cũ (a)
for master_id, dup_id, name in root_dups:
    # Ưu tiên giữ cái có đơn nhiều hơn, hoặc cái cũ hơn (ID nhỏ hơn)
    master_has = any_orders(master_id)
    dup_has    = any_orders(dup_id)

    if dup_has and has_recent_orders(dup_id):
        skip_list.append((dup_id, master_id, name,
                          f"dup có đơn gần đây (id={dup_id} > id={master_id})"))
    elif not dup_has and not has_recent_orders(dup_id):
        po, so, pick = count_orders(dup_id)
        safe_list.append((dup_id, master_id, name,
                          f"[loại2-root] PO={po} SO={so} pick={pick}"))
    else:
        po, so, pick = count_orders(dup_id)
        skip_list.append((dup_id, master_id, name,
                          f"dup có đơn (nhưng không gần đây) - xem thủ công PO={po}"))

print(f"\n  ✓ AN TOÀN để archive : {len(safe_list)}")
print(f"  ✗ SKIP (có đơn gần đây): {len(skip_list)}")

print(f"\n  --- SKIP LIST (cần xử lý thủ công) ---")
for dup_id, master_id, name, reason in skip_list[:30]:
    print(f"  dup={dup_id:>7}  master={master_id:>7}  {name[:55]:55}  {reason}")
if len(skip_list) > 30:
    print(f"  ... và {len(skip_list)-30} cặp khác")

print(f"\n  --- SAFE LIST ---")
for dup_id, master_id, name, reason in safe_list[:50]:
    print(f"  dup={dup_id:>7}  master={master_id:>7}  {name[:55]:55}  {reason}")
if len(safe_list) > 50:
    print(f"  ... và {len(safe_list)-50} cặp khác")

# ─── 3. THỰC HIỆN ────────────────────────────────────────────────────────────
if DRY_RUN:
    section("DRY RUN — Đổi DRY_RUN = False để thực thi")
    print(f"\n  Sẽ archive {len(safe_list)} records")
else:
    section(f"THỰC HIỆN ARCHIVE {len(safe_list)} records ...")

    archived = 0
    errors   = 0
    FIELDS_TO_CLEAR = ['vat', 'ref', 'company_registry', 'phone', 'mobile',
                       'email', 'street', 'city', 'zip']

    for dup_id, master_id, name, reason in safe_list:
        try:
            dup    = env['res.partner'].sudo().with_context(active_test=False).browse(dup_id)
            master = env['res.partner'].sudo().browse(master_id)

            # -- Chuyển ref / company_registry sang master nếu master chưa có --
            transferred = []
            if not master.ref and dup.ref:
                master.write({'ref': dup.ref})
                transferred.append(f"ref={dup.ref}")
            if not master.company_registry and dup.company_registry:
                master.write({'company_registry': dup.company_registry})
                transferred.append(f"company_registry={dup.company_registry}")
            if not master.vat and dup.vat:
                master.write({'vat': dup.vat})
                transferred.append(f"vat={dup.vat}")

            # -- Xóa trắng thông tin trên dup trước khi archive --
            clear_vals = {f: False for f in FIELDS_TO_CLEAR}
            clear_vals['active'] = False
            clear_vals['parent_id'] = False   # bỏ liên kết cha
            dup.write(clear_vals)

            msg = f"Archived as duplicate of id={master_id}. Transferred: {', '.join(transferred) or 'none'}"
            if transferred:
                master.message_post(body=msg)

            archived += 1
            print(f"  ✓ archive id={dup_id:>7}  → master={master_id:>7}  [{name[:50]}]"
                  + (f"  transferred: {', '.join(transferred)}" if transferred else ""))

        except Exception as e:
            errors += 1
            print(f"  ✗ LỖI id={dup_id}: {e}")

    env.cr.commit()
    print(f"\n  Đã commit. Archived={archived}  Errors={errors}")

    # -- Verify --
    section("VERIFY")
    cr.execute("""
        SELECT COUNT(*) FROM res_partner
        WHERE is_company = True AND active = True
          AND parent_id IS NOT NULL
          AND id IN %s
    """, (tuple(d for d, m, n, r in safe_list) or (0,),))
    remaining = cr.fetchone()[0]
    print(f"  Records vẫn còn active trong safe_list: {remaining}  (mong đợi: 0)")

print("\n  Done.")
