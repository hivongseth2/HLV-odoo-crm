#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script migrate điểm loyalty từ partner con về commercial_partner_id (công ty gốc).

Chạy trong Odoo shell:
    python odoo-bin shell -d <database> < custom_addons/hlv_loyalty/scripts/migrate_partner_points.py

Hoặc paste trực tiếp vào Odoo shell.
"""

import logging
_logger = logging.getLogger('loyalty.migrate')

print("=" * 60)
print("MIGRATE: Chuyển điểm loyalty về commercial_partner_id")
print("=" * 60)

# Lấy tất cả history records có partner_id là con (có parent/commercial partner khác)
histories = env['hlv.loyalty.history'].sudo().search([])

migrated = 0
skipped = 0

for h in histories:
    partner = h.partner_id
    root = partner.commercial_partner_id

    # Nếu đã là root (commercial == chính nó) → bỏ qua
    if not root or root.id == partner.id:
        skipped += 1
        continue

    _logger.info(
        "Migrate history #%d: %s (id=%d) → %s (id=%d) | %+d điểm | %s",
        h.id, partner.name, partner.id,
        root.name, root.id,
        h.point_amount, h.transaction_type,
    )
    h.sudo().write({'partner_id': root.id})
    migrated += 1

# Cũng migrate vouchers
print("\nMigrate vouchers...")
vouchers = env['hlv.loyalty.voucher'].sudo().search([])
voucher_migrated = 0
for v in vouchers:
    partner = v.partner_id
    root = partner.commercial_partner_id
    if not root or root.id == partner.id:
        continue
    _logger.info(
        "Migrate voucher #%d [%s]: %s → %s",
        v.id, v.code, partner.name, root.name,
    )
    v.sudo().write({'partner_id': root.id})
    voucher_migrated += 1

# Recompute loyalty_total_points cho tất cả partner bị ảnh hưởng
print("\nRecompute loyalty_total_points...")
affected_partners = env['hlv.loyalty.history'].sudo().search([]).mapped('partner_id')
affected_partners._compute_loyalty_total_points()
affected_partners._compute_loyalty_tier()

env.cr.commit()

print("\n" + "=" * 60)
print(f"✓ History records migrated : {migrated}")
print(f"  History records skipped   : {skipped}")
print(f"✓ Vouchers migrated         : {voucher_migrated}")
print(f"✓ Partners recomputed       : {len(affected_partners)}")
print("=" * 60)
print("DONE. Đã commit vào database.")
