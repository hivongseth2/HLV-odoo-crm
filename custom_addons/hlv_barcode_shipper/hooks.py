# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def pre_init_hook(env):
    """
    Pre-init hook: Tạo columns trong DB TRƯỚC khi module load.
    Điều này đảm bảo fields tồn tại trước khi views được validate.
    """
    _logger.info("HLV Barcode Shipper: Running pre_init_hook...")
    cr = env.cr
    
    columns_to_add = [
        ("hlv_barcode_skip_package_scan", "BOOLEAN DEFAULT FALSE"),
        ("hlv_barcode_skip_product_scan", "BOOLEAN DEFAULT FALSE"),
    ]
    
    for column_name, column_def in columns_to_add:
        cr.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'res_company' 
            AND column_name = %s
        """, (column_name,))
        
        if not cr.fetchone():
            _logger.info(f"HLV Barcode Shipper: Adding column '{column_name}' to res_company...")
            cr.execute(f"ALTER TABLE res_company ADD COLUMN {column_name} {column_def}")
            _logger.info(f"HLV Barcode Shipper: Column '{column_name}' added successfully.")
        else:
            _logger.info(f"HLV Barcode Shipper: Column '{column_name}' already exists, skipping.")

