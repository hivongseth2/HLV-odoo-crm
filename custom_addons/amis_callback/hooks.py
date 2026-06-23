# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def pre_init_hook(env):
    """Bootstrap newly added wizard tables for one-shot Odoo.sh full builds."""
    _logger.info("AMIS Callback: ensuring Shopee reconciliation wizard tables exist...")
    cr = env.cr
    cr.execute("""
        CREATE TABLE IF NOT EXISTS shopee_meinvoice_reconcile_wizard (
            id SERIAL PRIMARY KEY
        )
    """)
    cr.execute("""
        CREATE TABLE IF NOT EXISTS shopee_meinvoice_reconcile_wizard_line (
            id SERIAL PRIMARY KEY
        )
    """)
