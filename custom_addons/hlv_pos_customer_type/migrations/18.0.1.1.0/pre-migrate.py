# -*- coding: utf-8 -*-
"""
Pre-migration script for hlv_pos_customer_type
Runs BEFORE models are loaded during upgrade
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """
    Backup old Selection values before column type change.
    This runs before Odoo tries to alter the column.
    """
    if not version:
        # Fresh install, no migration needed
        return
    
    _logger.info("Pre-migration: Checking pos_customer_type column...")
    
    # Check if the column exists and is varchar (Selection)
    cr.execute("""
        SELECT data_type 
        FROM information_schema.columns 
        WHERE table_name = 'res_partner' AND column_name = 'pos_customer_type'
    """)
    result = cr.fetchone()
    
    if result and result[0] in ('character varying', 'text'):
        _logger.info("Pre-migration: Found old Selection column, backing up data...")
        
        # Create temp column to store old values
        cr.execute("""
            ALTER TABLE res_partner 
            ADD COLUMN IF NOT EXISTS pos_customer_type_old VARCHAR
        """)
        
        # Copy old values to temp column
        cr.execute("""
            UPDATE res_partner 
            SET pos_customer_type_old = pos_customer_type
            WHERE pos_customer_type IS NOT NULL
        """)
        
        # Drop the old column so Odoo can recreate it as integer
        cr.execute("""
            ALTER TABLE res_partner 
            DROP COLUMN pos_customer_type
        """)
        
        _logger.info("Pre-migration: Backup completed, old column dropped")
    else:
        _logger.info("Pre-migration: Column already integer or doesn't exist, skipping")
