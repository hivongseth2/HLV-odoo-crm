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

    company_columns = [
        ("hlv_barcode_skip_package_scan", "BOOLEAN DEFAULT FALSE"),
        ("hlv_barcode_skip_product_scan", "BOOLEAN DEFAULT FALSE"),
        ("hlv_barcode_receive_require_detail_scan", "BOOLEAN DEFAULT FALSE"),
        ("hlv_barcode_receive_skip_package_scan", "BOOLEAN DEFAULT FALSE"),
        ("hlv_barcode_receive_skip_product_scan", "BOOLEAN DEFAULT FALSE"),
        ("hlv_barcode_return_require_detail_scan", "BOOLEAN DEFAULT FALSE"),
        ("hlv_barcode_return_skip_package_scan", "BOOLEAN DEFAULT FALSE"),
        ("hlv_barcode_return_skip_product_scan", "BOOLEAN DEFAULT FALSE"),
        ("hlv_barcode_google_maps_api_key", "VARCHAR"),
    ]

    for column_name, column_def in company_columns:
        cr.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'res_company'
            AND column_name = %s
        """, (column_name,))
        if not cr.fetchone():
            _logger.info(f"HLV Barcode Shipper: Adding res_company column '{column_name}'...")
            cr.execute(f"ALTER TABLE res_company ADD COLUMN {column_name} {column_def}")

    picking_columns = [
        ("shipper_received", "BOOLEAN DEFAULT FALSE"),
        ("shipper_receive_time", "TIMESTAMP WITHOUT TIME ZONE"),
        ("shipper_received_by", "INTEGER"),
        ("shipper_returned", "BOOLEAN DEFAULT FALSE"),
        ("shipper_return_time", "TIMESTAMP WITHOUT TIME ZONE"),
        ("shipper_return_reason", "VARCHAR"),
    ]

    for column_name, column_def in picking_columns:
        cr.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'stock_picking'
            AND column_name = %s
        """, (column_name,))
        if not cr.fetchone():
            _logger.info(f"HLV Barcode Shipper: Adding stock_picking column '{column_name}'...")
            cr.execute(f"ALTER TABLE stock_picking ADD COLUMN {column_name} {column_def}")

