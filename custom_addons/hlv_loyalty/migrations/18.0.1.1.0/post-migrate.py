# -*- coding: utf-8 -*-
"""
Migration 18.0.1.1.0 - Chuyển điểm loyalty về commercial_partner_id.

Chạy tự động khi: odoo-bin -u hlv_loyalty
"""
import logging
from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        # Fresh install - không có dữ liệu cũ cần migrate
        return

    env = api.Environment(cr, SUPERUSER_ID, {})

    _logger.info("Loyalty migration: chuyển điểm về commercial_partner_id...")

    # ── Migrate history records ────────────────────────────────────────────────
    histories = env['hlv.loyalty.history'].search([])
    migrated_h = 0
    skipped_h = 0
    affected_partner_ids = set()

    for h in histories:
        partner = h.partner_id
        root = partner.commercial_partner_id
        if not root or root.id == partner.id:
            skipped_h += 1
            affected_partner_ids.add(partner.id)
            continue
        _logger.info(
            "History #%d: %s → %s | %+d pts | %s",
            h.id, partner.name, root.name, h.point_amount, h.transaction_type,
        )
        h.write({'partner_id': root.id})
        affected_partner_ids.add(root.id)
        migrated_h += 1

    # ── Migrate vouchers ───────────────────────────────────────────────────────
    vouchers = env['hlv.loyalty.voucher'].search([])
    migrated_v = 0

    for v in vouchers:
        partner = v.partner_id
        root = partner.commercial_partner_id
        if not root or root.id == partner.id:
            continue
        _logger.info("Voucher #%d [%s]: %s → %s", v.id, v.code, partner.name, root.name)
        v.write({'partner_id': root.id})
        affected_partner_ids.add(root.id)
        migrated_v += 1

    # ── Recompute fields trên các partner bị ảnh hưởng ────────────────────────
    if affected_partner_ids:
        partners = env['res.partner'].browse(list(affected_partner_ids))
        partners._compute_loyalty_total_points()
        partners._compute_loyalty_tier()

    _logger.info(
        "Loyalty migration done: %d history migrated, %d skipped, "
        "%d vouchers migrated, %d partners recomputed.",
        migrated_h, skipped_h, migrated_v, len(affected_partner_ids),
    )
