#!/usr/bin/env python3
"""
Sync hlv_inventory_group_report legacy group-product relation from current data.

Run inside Odoo shell:

    python odoo-bin shell -d <DB_NAME> --no-http < bin/sync_hlv_group_legacy_rel_from_current.py

Preview without committing:

    $env:DRY_RUN = "1"
    python odoo-bin shell -d <DB_NAME> --no-http < bin/sync_hlv_group_legacy_rel_from_current.py
    Remove-Item Env:DRY_RUN
"""

import os


CURRENT_TABLE = "hlv_product_report_group_line"
LEGACY_TABLE = "hlv_report_group_product_rel"
MIGRATION_PARAM = "hlv_inventory_group_report.legacy_many2many_migrated"
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in {"1", "true", "yes", "y"}


def table_exists(table_name):
    env.cr.execute("SELECT to_regclass(%s)", (table_name,))
    return bool(env.cr.fetchone()[0])


def scalar(sql, params=None):
    env.cr.execute(sql, params or ())
    row = env.cr.fetchone()
    return row[0] if row else 0


def print_group_counts(title, table_name):
    env.cr.execute(
        """
        SELECT rel.group_id, grp.name, COUNT(*) AS product_count
        FROM %s rel
        LEFT JOIN hlv_product_report_group grp ON grp.id = rel.group_id
        GROUP BY rel.group_id, grp.name
        ORDER BY rel.group_id
        """
        % table_name
    )
    rows = env.cr.fetchall()
    print("\n%s" % title)
    if not rows:
        print("  (empty)")
        return
    for group_id, group_name, product_count in rows:
        print("  group_id=%s | products=%s | name=%s" % (group_id, product_count, group_name or ""))


def count_legacy_only():
    return scalar(
        """
        SELECT COUNT(*)
        FROM %s rel
        WHERE NOT EXISTS (
            SELECT 1
            FROM %s line
            WHERE line.group_id = rel.group_id
              AND line.product_id = rel.product_id
        )
        """
        % (LEGACY_TABLE, CURRENT_TABLE)
    )


def count_missing_in_legacy():
    return scalar(
        """
        SELECT COUNT(*)
        FROM %s line
        WHERE NOT EXISTS (
            SELECT 1
            FROM %s rel
            WHERE rel.group_id = line.group_id
              AND rel.product_id = line.product_id
        )
        """
        % (CURRENT_TABLE, LEGACY_TABLE)
    )


def count_legacy_duplicates():
    return scalar(
        """
        SELECT COALESCE(SUM(dup_count - 1), 0)
        FROM (
            SELECT group_id, product_id, COUNT(*) AS dup_count
            FROM %s
            GROUP BY group_id, product_id
            HAVING COUNT(*) > 1
        ) dups
        """
        % LEGACY_TABLE
    )


print("Sync HLV inventory group legacy relation from current group lines")
print("DRY_RUN=%s" % ("yes" if DRY_RUN else "no"))

if not table_exists(CURRENT_TABLE):
    print("ERROR: current table %s does not exist." % CURRENT_TABLE)
    raise SystemExit(1)

current_count = scalar("SELECT COUNT(*) FROM %s" % CURRENT_TABLE)
print("Current table %s rows: %s" % (CURRENT_TABLE, current_count))

if not table_exists(LEGACY_TABLE):
    print("Legacy table %s does not exist; nothing to sync." % LEGACY_TABLE)
    env["ir.config_parameter"].sudo().set_param(MIGRATION_PARAM, "1")
    if DRY_RUN:
        env.cr.rollback()
        print("Rolled back marker update because DRY_RUN=1.")
    else:
        env.cr.commit()
        print("Committed migration marker: %s=1" % MIGRATION_PARAM)
    raise SystemExit(0)

legacy_before = scalar("SELECT COUNT(*) FROM %s" % LEGACY_TABLE)
legacy_only = count_legacy_only()
missing_in_legacy = count_missing_in_legacy()
legacy_duplicates = count_legacy_duplicates()

print("Legacy table %s rows before: %s" % (LEGACY_TABLE, legacy_before))
print("Legacy-only stale rows to remove: %s" % legacy_only)
print("Current rows missing in legacy: %s" % missing_in_legacy)
print("Legacy duplicate rows to collapse: %s" % legacy_duplicates)
print_group_counts("Current group counts", CURRENT_TABLE)
print_group_counts("Legacy group counts before", LEGACY_TABLE)

env.cr.execute("DELETE FROM %s" % LEGACY_TABLE)
env.cr.execute(
    """
    INSERT INTO hlv_report_group_product_rel (group_id, product_id)
    SELECT DISTINCT line.group_id, line.product_id
    FROM hlv_product_report_group_line line
    JOIN hlv_product_report_group grp ON grp.id = line.group_id
    JOIN product_product prod ON prod.id = line.product_id
    WHERE line.group_id IS NOT NULL
      AND line.product_id IS NOT NULL
    """
)
env["ir.config_parameter"].sudo().set_param(MIGRATION_PARAM, "1")

legacy_after = scalar("SELECT COUNT(*) FROM %s" % LEGACY_TABLE)
print_group_counts("Legacy group counts after", LEGACY_TABLE)
print("\nLegacy table %s rows after: %s" % (LEGACY_TABLE, legacy_after))
print("Migration marker set: %s=1" % MIGRATION_PARAM)

if DRY_RUN:
    env.cr.rollback()
    print("DRY_RUN=1, rolled back all changes.")
else:
    env.cr.commit()
    print("Committed legacy relation sync.")
