# -*- coding: utf-8 -*-
"""
Post-migration script for hlv_pos_customer_type
Runs AFTER models are loaded during upgrade
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """
    Restore old Selection values as Many2one IDs after upgrade.
    """
    if not version:
        return
    
    _logger.info("Post-migration: Checking for backed up data...")
    
    # Check if we have the backup column
    cr.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'res_partner' AND column_name = 'pos_customer_type_old'
    """)
    
    if not cr.fetchone():
        _logger.info("Post-migration: No backup column found, skipping")
        return
    
    _logger.info("Post-migration: Restoring pos_customer_type values...")
    
    # Get customer type IDs by code
    cr.execute("""
        SELECT id, code FROM pos_customer_type WHERE code IN ('cash', 'bank')
    """)
    type_mapping = {row[1]: row[0] for row in cr.fetchall()}
    
    # Update partners with old 'cash' value
    if 'cash' in type_mapping:
        cr.execute("""
            UPDATE res_partner 
            SET pos_customer_type = %s
            WHERE pos_customer_type_old = 'cash'
        """, (type_mapping['cash'],))
        _logger.info(f"Post-migration: Migrated 'cash' to ID {type_mapping['cash']}")
    
    # Update partners with old 'bank' value  
    if 'bank' in type_mapping:
        cr.execute("""
            UPDATE res_partner 
            SET pos_customer_type = %s
            WHERE pos_customer_type_old = 'bank'
        """, (type_mapping['bank'],))
        _logger.info(f"Post-migration: Migrated 'bank' to ID {type_mapping['bank']}")
    
    # Drop the temporary column
    cr.execute("""
        ALTER TABLE res_partner 
        DROP COLUMN IF EXISTS pos_customer_type_old
    """)
    
    _logger.info("Post-migration: Migration completed successfully")
