# -*- coding: utf-8 -*-
"""
Migration 18.0.1.3.0
- Add loyalty_default_discount column to res_partner (% chiết khấu mặc định Loyalty)
- Add discount_per_point column to hlv_loyalty_program (số tiền chiết khấu / điểm)
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # 1. Add loyalty_default_discount to res_partner
    cr.execute("""
        ALTER TABLE res_partner
        ADD COLUMN IF NOT EXISTS loyalty_default_discount numeric DEFAULT 5.0;
    """)
    _logger.info("migration 18.0.1.3.0: added loyalty_default_discount to res_partner")

    # 2. Add discount_per_point to hlv_loyalty_program
    cr.execute("""
        ALTER TABLE hlv_loyalty_program
        ADD COLUMN IF NOT EXISTS discount_per_point numeric DEFAULT 10000;
    """)
    _logger.info("migration 18.0.1.3.0: added discount_per_point to hlv_loyalty_program")
    _logger.info("migration 18.0.1.3.0: done")
