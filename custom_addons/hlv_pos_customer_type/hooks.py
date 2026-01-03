# -*- coding: utf-8 -*-
import logging
from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def pre_init_hook(env):
    """
    Pre-init hook to handle migration from Selection to Many2one.
    Store old values before column type change.
    """
    cr = env.cr
    cr.execute("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'res_partner' AND column_name = 'pos_customer_type'
    """)
    result = cr.fetchone()
    
    if result and result[1] in ('character varying', 'text'):
        _logger.info("Migrating pos_customer_type from Selection to Many2one...")
        
        # Create temp column to store old values
        cr.execute("""
            ALTER TABLE res_partner 
            ADD COLUMN IF NOT EXISTS pos_customer_type_old VARCHAR
        """)
        
        # Copy old values
        cr.execute("""
            UPDATE res_partner 
            SET pos_customer_type_old = pos_customer_type
            WHERE pos_customer_type IS NOT NULL
        """)
        
        # Drop the old column to allow Odoo to recreate it as integer
        cr.execute("""
            ALTER TABLE res_partner 
            DROP COLUMN IF EXISTS pos_customer_type
        """)
        
        _logger.info("Old pos_customer_type values backed up to pos_customer_type_old")


def post_init_hook(env):
    """
    Post-init hook to migrate old Selection values to new Many2one.
    """
    cr = env.cr
    
    # Check if we have old data to migrate
    cr.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'res_partner' AND column_name = 'pos_customer_type_old'
    """)
    
    if not cr.fetchone():
        return
    
    _logger.info("Restoring pos_customer_type values from backup...")
    
    # Get the IDs of customer types by code
    CustomerType = env['pos.customer.type']
    
    type_mapping = {}
    for type_rec in CustomerType.search([]):
        if type_rec.code:
            type_mapping[type_rec.code] = type_rec.id
    
    # Update partners with old 'cash' value
    if 'cash' in type_mapping:
        cr.execute("""
            UPDATE res_partner 
            SET pos_customer_type = %s
            WHERE pos_customer_type_old = 'cash'
        """, (type_mapping['cash'],))
        _logger.info(f"Migrated 'cash' to ID {type_mapping['cash']}")
    
    # Update partners with old 'bank' value
    if 'bank' in type_mapping:
        cr.execute("""
            UPDATE res_partner 
            SET pos_customer_type = %s
            WHERE pos_customer_type_old = 'bank'
        """, (type_mapping['bank'],))
        _logger.info(f"Migrated 'bank' to ID {type_mapping['bank']}")
    
    # Drop the temporary column
    cr.execute("""
        ALTER TABLE res_partner 
        DROP COLUMN IF EXISTS pos_customer_type_old
    """)
    
    _logger.info("pos_customer_type migration completed successfully")
