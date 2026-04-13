# hlv_barcode_shipper/migrations/18.0.2.0.0/pre-migrate.py
"""
Add new columns for receive/return shipper features to res_company and stock_picking.
Using ADD COLUMN IF NOT EXISTS to be safe in case a partial upgrade already ran.
"""


def migrate(cr, version):
    # === res_company: receive/return config flags ===
    company_columns = [
        ("hlv_barcode_receive_require_detail_scan", "boolean", "false"),
        ("hlv_barcode_receive_skip_package_scan", "boolean", "false"),
        ("hlv_barcode_receive_skip_product_scan", "boolean", "false"),
        ("hlv_barcode_return_require_detail_scan", "boolean", "false"),
        ("hlv_barcode_return_skip_package_scan", "boolean", "false"),
        ("hlv_barcode_return_skip_product_scan", "boolean", "false"),
    ]
    for col, col_type, default in company_columns:
        cr.execute(
            f"""
            ALTER TABLE res_company
            ADD COLUMN IF NOT EXISTS {col} {col_type} DEFAULT {default};
            """
        )

    # === stock_picking: shipper receive/return tracking fields ===
    picking_columns = [
        ("shipper_received", "boolean", "false"),
        ("shipper_receive_time", "timestamp without time zone", None),
        ("shipper_received_by", "integer", None),
        ("shipper_returned", "boolean", "false"),
        ("shipper_return_time", "timestamp without time zone", None),
        ("shipper_return_reason", "varchar", None),
    ]
    for col, col_type, default in picking_columns:
        if default is not None:
            cr.execute(
                f"""
                ALTER TABLE stock_picking
                ADD COLUMN IF NOT EXISTS {col} {col_type} DEFAULT {default};
                """
            )
        else:
            cr.execute(
                f"""
                ALTER TABLE stock_picking
                ADD COLUMN IF NOT EXISTS {col} {col_type};
                """
            )
