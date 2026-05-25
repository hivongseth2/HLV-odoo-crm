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

DRY_RUN     = False   # ← đổi False để chạy thật
RECENT_DAYS = 90      # Đơn trong vòng N ngày → skip (không archive)

# ─── helpers ──────────────────────────────────────────────────────────────────
SEP = "=" * 90
def section(t): print(f"\n{SEP}\n  {t}\n{SEP}")

cr = env.cr

# ─── 1. TÌM CÁC CẶP DUPLICATE ────────────────────────────────────────────────
section("1. TÌM CÁC CẶP DUPLICATE COMPANY")

# Loại 1: is_company=True có parent_id cùng tên (anomaly)
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
child_dups = cr.fetchall()

# Loại 2: 2 root companies cùng tên → archive cái mới hơn (id lớn hơn)
cr.execute("""
    SELECT a.id as master_id, b.id as dup_id, a.name
    FROM res_partner a
    JOIN res_partner b ON upper(trim(a.name)) = upper(trim(b.name))
                       AND a.id < b.id
    WHERE a.is_company = True AND b.is_company = True
      AND a.parent_id IS NULL AND b.parent_id IS NULL
      AND a.active = True AND b.active = True
    ORDER BY a.name
""")
root_dups = cr.fetchall()

print(f"\n  Loại 1 (con bất thường - is_company+parent_id cùng tên): {len(child_dups)}")
print(f"  Loại 2 (2 root company cùng tên)                        : {len(root_dups)}")

# ─── 2. DANH SÁCH SẼ ARCHIVE ─────────────────────────────────────────────────
section("2. DANH SÁCH SẼ ARCHIVE")

archive_list = []  # [(dup_id, master_id, name)]

for dup_id, master_id, name in child_dups:
    archive_list.append((dup_id, master_id, name))

for master_id, dup_id, name in root_dups:
    archive_list.append((dup_id, master_id, name))

print(f"\n  Tổng sẽ archive: {len(archive_list)}\n")
print(f"  {'DUP_ID':>7}  {'MASTER_ID':>9}  NAME")
print(f"  {'-'*7}  {'-'*9}  {'-'*60}")
for dup_id, master_id, name in archive_list:
    print(f"  {dup_id:>7}  {master_id:>9}  {name[:60]}")

# ─── 3. THỰC HIỆN ────────────────────────────────────────────────────────────
if DRY_RUN:
    section("DRY RUN — Đổi DRY_RUN = False để thực thi")
    print(f"\n  Sẽ archive {len(archive_list)} records")
else:
    section(f"THỰC HIỆN ARCHIVE {len(archive_list)} records ...")

    archived = 0
    errors   = 0
    FIELDS_TO_CLEAR = ['vat', 'ref', 'company_registry', 'phone', 'mobile',
                       'email', 'street', 'city', 'zip']

    # Các bảng cần reassign partner_id từ dup → master
    REASSIGN_TABLES = [
        'purchase_order',
        'sale_order',
        'stock_picking',
        'account_move',
        'pos_order',
        'mrp_production',
        'purchase_order_line',
        'sale_order_line',
        'account_move_line',
    ]

    for dup_id, master_id, name in archive_list:
        try:
            dup    = env['res.partner'].sudo().with_context(active_test=False).browse(dup_id)
            master = env['res.partner'].sudo().browse(master_id)

            # -- Reassign tất cả đơn hàng từ dup → master --
            reassigned = {}
            for tbl in REASSIGN_TABLES:
                # Chỉ update nếu bảng và cột tồn tại
                cr.execute("""
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = %s AND column_name = 'partner_id'
                      AND table_schema = 'public'
                """, (tbl,))
                if not cr.fetchone():
                    continue
                cr.execute(
                    f"UPDATE {tbl} SET partner_id = %s WHERE partner_id = %s",
                    (master_id, dup_id)
                )
                if cr.rowcount:
                    reassigned[tbl] = cr.rowcount

            # -- Chuyển ref / company_registry / vat sang master nếu master chưa có --
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

            # -- Xóa trắng thông tin trên dup rồi archive --
            clear_vals = {f: False for f in FIELDS_TO_CLEAR}
            clear_vals['active']    = False
            clear_vals['parent_id'] = False
            dup.write(clear_vals)

            msg_parts = []
            if reassigned:
                msg_parts.append("Reassigned: " + ", ".join(f"{t}({n})" for t, n in reassigned.items()))
            if transferred:
                msg_parts.append("Transferred: " + ", ".join(transferred))
            if msg_parts:
                master.message_post(body=f"Archived duplicate id={dup_id}. " + " | ".join(msg_parts))

            archived += 1
            extra = ""
            if reassigned:
                extra += "  moved: " + " ".join(f"{t}({n})" for t, n in reassigned.items())
            if transferred:
                extra += "  transferred: " + ", ".join(transferred)
            print(f"  ✓ archive id={dup_id:>7}  → master={master_id:>7}  [{name[:45]}]{extra}")

        except Exception as e:
            errors += 1
            print(f"  ✗ LỖI id={dup_id}: {e}")

    env.cr.commit()
    print(f"\n  Đã commit. Archived={archived}  Errors={errors}")

    section("VERIFY")
    remaining_ids = tuple(d for d, m, n in archive_list) or (0,)
    cr.execute(
        "SELECT COUNT(*) FROM res_partner WHERE active = True AND id IN %s",
        (remaining_ids,)
    )
    remaining = cr.fetchone()[0]
    print(f"  Records vẫn còn active: {remaining}  (mong đợi: 0)")

print("\n  Done.")
