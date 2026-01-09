# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def pre_init_hook(env):
    """
    Pre-init hook: Tạo column trong DB TRƯỚC khi module load.
    Điều này đảm bảo field tồn tại trước khi views được validate.
    """
    _logger.info("HLV Barcode Shipper: Running pre_init_hook...")
    cr = env.cr
    
    # Check if column exists
    cr.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'res_company' 
        AND column_name = 'hlv_barcode_shipper_allow_package'
    """)
    
    if not cr.fetchone():
        _logger.info("HLV Barcode Shipper: Adding column 'hlv_barcode_shipper_allow_package' to res_company...")
        cr.execute("""
            ALTER TABLE res_company 
            ADD COLUMN hlv_barcode_shipper_allow_package BOOLEAN DEFAULT TRUE
        """)
        _logger.info("HLV Barcode Shipper: Column added successfully.")
    else:
        _logger.info("HLV Barcode Shipper: Column already exists, skipping.")
