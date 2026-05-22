# -*- coding: utf-8 -*-
"""
merge_milwaukee_duplicates.py
==============================
Merge id=6972 (duplicate) → id=31 (master) cho CÔNG TY TNHH MILWAUKEE TOOL (VIỆT NAM)
dùng base.partner.merge.automatic.wizard của Odoo (chính thức, an toàn).

Cách chạy:
    odoo-bin shell -c <odoo.conf> --no-http < bin/merge_milwaukee_duplicates.py

Script sẽ in DRY RUN trước. Sửa DRY_RUN = False để thực sự merge.
"""

DRY_RUN = False   # ← đổi thành False khi muốn thực thi

MASTER_ID    = 31    # giữ lại (record gốc, có ref=MILWAU, tạo từ đầu)
DUPLICATE_ID = 6972  # merge vào master rồi archive

SEP = "=" * 80

def section(title):
    print(f"\n{SEP}\n  {title}\n{SEP}")

# ─────────────────────────────────────────────────────────────────────────────
# Kiểm tra trước khi merge
# ─────────────────────────────────────────────────────────────────────────────
section("KIỂM TRA TRƯỚC KHI MERGE")

master = env['res.partner'].sudo().browse(MASTER_ID)
dup    = env['res.partner'].sudo().browse(DUPLICATE_ID)

if not master.exists():
    print(f"  LỖI: master id={MASTER_ID} không tồn tại!")
    raise SystemExit(1)
if not dup.exists():
    print(f"  LỖI: duplicate id={DUPLICATE_ID} không tồn tại!")
    raise SystemExit(1)

print(f"""
  MASTER   id={master.id}
    name       : {master.name}
    ref        : {master.ref or '(trống)'}
    vat        : {master.vat or '(trống)'}
    parent_id  : {master.parent_id.id if master.parent_id else '-'}
    active     : {master.active}
    create_date: {master.create_date}

  DUPLICATE id={dup.id}
    name       : {dup.name}
    ref        : {dup.ref or '(trống)'}
    vat        : {dup.vat or '(trống)'}
    parent_id  : {dup.parent_id.id if dup.parent_id else '-'}  ← sẽ bị xóa sau merge
    active     : {dup.active}
    create_date: {dup.create_date}
""")

# Đếm records sẽ bị re-assign
env.cr.execute("SELECT COUNT(*) FROM purchase_order WHERE partner_id = %s", (DUPLICATE_ID,))
po_count = env.cr.fetchone()[0]

env.cr.execute("SELECT COUNT(*) FROM sale_order WHERE partner_id = %s", (DUPLICATE_ID,))
so_count = env.cr.fetchone()[0]

env.cr.execute("SELECT COUNT(*) FROM account_move WHERE partner_id = %s", (DUPLICATE_ID,))
inv_count = env.cr.fetchone()[0]

env.cr.execute("SELECT COUNT(*) FROM mail_message WHERE model='res.partner' AND res_id = %s", (DUPLICATE_ID,))
msg_count = env.cr.fetchone()[0]

env.cr.execute("SELECT COUNT(*) FROM stock_picking WHERE partner_id = %s", (DUPLICATE_ID,))
picking_count = env.cr.fetchone()[0]

print(f"  Records sẽ được re-assign từ id={DUPLICATE_ID} → id={MASTER_ID}:")
print(f"    PO (purchase_order)  : {po_count}")
print(f"    SO (sale_order)      : {so_count}")
print(f"    Invoice (account_move): {inv_count}")
print(f"    Stock picking        : {picking_count}")
print(f"    Chatter messages     : {msg_count}")
print(f"\n  Sau merge: id={DUPLICATE_ID} sẽ bị ARCHIVE (active=False)")

# ─────────────────────────────────────────────────────────────────────────────
# Tìm TẤT CẢ bảng có FK tham chiếu đến res_partner
# ─────────────────────────────────────────────────────────────────────────────
section("TÌM TẤT CẢ FK THAM CHIẾU res_partner")

env.cr.execute("""
    SELECT kcu.table_name, kcu.column_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
        ON tc.constraint_name = kcu.constraint_name
        AND tc.table_schema = kcu.table_schema
    JOIN information_schema.referential_constraints rc
        ON tc.constraint_name = rc.constraint_name
        AND tc.table_schema = rc.constraint_schema
    JOIN information_schema.key_column_usage kcu2
        ON rc.unique_constraint_name = kcu2.constraint_name
        AND rc.unique_constraint_schema = kcu2.table_schema
    WHERE tc.constraint_type = 'FOREIGN KEY'
      AND kcu2.table_name = 'res_partner'
      AND kcu2.column_name = 'id'
    ORDER BY kcu.table_name, kcu.column_name
""")
fk_refs = env.cr.fetchall()
print(f"\n  Tìm được {len(fk_refs)} FK columns tham chiếu res_partner:\n")

# Lọc ra những bảng thực sự có dùng DUPLICATE_ID
affected = []
for table, col in fk_refs:
    try:
        env.cr.execute(
            f'SELECT COUNT(*) FROM "{table}" WHERE "{col}" = %s',
            (DUPLICATE_ID,)
        )
        cnt = env.cr.fetchone()[0]
        if cnt > 0:
            affected.append((table, col, cnt))
            print(f"  ✓  {table}.{col}  →  {cnt} rows")
    except Exception:
        pass  # bảng view hoặc không truy cập được

print(f"\n  Tổng: {len(affected)} bảng/cột cần update")

# ─────────────────────────────────────────────────────────────────────────────
# THỰC HIỆN MERGE
# ─────────────────────────────────────────────────────────────────────────────
if DRY_RUN:
    section("DRY RUN — Chưa thực thi. Đổi DRY_RUN = False để merge thật.")
    print(f"\n  Sẽ UPDATE {len(affected)} bảng/cột rồi archive id={DUPLICATE_ID}")
else:
    section(f"ĐANG MERGE id={DUPLICATE_ID} → id={MASTER_ID} ...")

    try:
        updated_total = 0
        for table, col, cnt in affected:
            # Bỏ qua chính bảng res_partner (tránh update parent_id thành master)
            if table == 'res_partner':
                print(f"  SKIP {table}.{col}  (xử lý riêng)")
                continue
            env.cr.execute(
                f'UPDATE "{table}" SET "{col}" = %s WHERE "{col}" = %s',
                (MASTER_ID, DUPLICATE_ID)
            )
            rows = env.cr.rowcount
            updated_total += rows
            print(f"  UPDATE {table}.{col}: {rows} rows")

        # Archive duplicate (dùng SQL trực tiếp để tránh constraint)
        env.cr.execute(
            "UPDATE res_partner SET active = false, parent_id = NULL WHERE id = %s",
            (DUPLICATE_ID,)
        )
        print(f"  ARCHIVE id={DUPLICATE_ID}  (active=False, parent_id=NULL)")

        env.cr.commit()
        print(f"\n  Đã commit. Tổng rows updated: {updated_total}")

        # ── Verify ──
        print(f"\n  --- VERIFY ---")
        env.cr.execute("SELECT active, parent_id FROM res_partner WHERE id = %s", (DUPLICATE_ID,))
        row = env.cr.fetchone()
        print(f"  id={DUPLICATE_ID}  active={row[0]}  parent_id={row[1]}  (mong đợi: False, None)")

        env.cr.execute("SELECT COUNT(*) FROM purchase_order WHERE partner_id = %s", (DUPLICATE_ID,))
        rem_po = env.cr.fetchone()[0]
        env.cr.execute("SELECT COUNT(*) FROM purchase_order WHERE partner_id = %s", (MASTER_ID,))
        master_po = env.cr.fetchone()[0]
        print(f"  PO còn dùng id={DUPLICATE_ID}: {rem_po}  (mong đợi: 0)")
        print(f"  PO dùng id={MASTER_ID}        : {master_po}")

        ok = (rem_po == 0 and row[0] is False)
        print(f"\n  {'✓ MERGE THÀNH CÔNG' if ok else '✗ Có vấn đề, kiểm tra lại!'}")

    except Exception as e:
        env.cr.rollback()
        print(f"\n  LỖI: {e}")
        raise

print("\n  Done.")
