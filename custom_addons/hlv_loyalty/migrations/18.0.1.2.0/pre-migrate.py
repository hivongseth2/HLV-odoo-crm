# -*- coding: utf-8 -*-
"""
Migration 18.0.1.2.0
- Add portal_phone column to hlv_loyalty_portal_account
- Populate from res_partner.phone for existing records (normalized)
- Add loyalty_portal_default_password column to res_company
"""
import re
import logging

_logger = logging.getLogger(__name__)


def _normalize_phone(phone):
    if not phone:
        return ''
    digits = re.sub(r'\D', '', phone)
    if len(digits) == 11 and digits.startswith('84'):
        digits = '0' + digits[2:]
    elif len(digits) == 12 and digits.startswith('084'):
        digits = '0' + digits[3:]
    return digits


def migrate(cr, version):
    # 1. Add portal_phone column if not exists
    cr.execute("""
        ALTER TABLE hlv_loyalty_portal_account
        ADD COLUMN IF NOT EXISTS portal_phone VARCHAR;
    """)

    # 2. Populate from partner phone for existing accounts
    cr.execute("""
        UPDATE hlv_loyalty_portal_account a
        SET portal_phone = p.phone
        FROM res_partner p
        WHERE a.partner_id = p.id
          AND a.portal_phone IS NULL
          AND p.phone IS NOT NULL
    """)
    cr.execute("SELECT id, portal_phone FROM hlv_loyalty_portal_account WHERE portal_phone IS NOT NULL")
    rows = cr.fetchall()
    for row_id, raw_phone in rows:
        normalized = _normalize_phone(raw_phone)
        if normalized != raw_phone:
            cr.execute(
                "UPDATE hlv_loyalty_portal_account SET portal_phone = %s WHERE id = %s",
                (normalized, row_id)
            )
    _logger.info("migration 18.0.1.2.0: portal_phone populated for %d records", len(rows))

    # 3. Add index on portal_phone
    cr.execute("""
        CREATE INDEX IF NOT EXISTS hlv_loyalty_portal_account_portal_phone_idx
        ON hlv_loyalty_portal_account (portal_phone);
    """)

    # 4. Add loyalty_portal_default_password to res_company if not exists
    cr.execute("""
        ALTER TABLE res_company
        ADD COLUMN IF NOT EXISTS loyalty_portal_default_password VARCHAR DEFAULT 'hlv@2026';
    """)
    _logger.info("migration 18.0.1.2.0: done")
