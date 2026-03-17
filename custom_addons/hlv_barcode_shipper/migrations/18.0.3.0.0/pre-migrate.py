# hlv_barcode_shipper/migrations/18.0.3.0.0/pre-migrate.py
"""
Ensure all receive/return shipper columns exist before ORM loads.
Uses IF NOT EXISTS so it's safe to run even if a partial upgrade already created some columns.
"""


def migrate(cr, version):
    # === res_company: receive/return config flags ===
    company_columns = [
        ("hlv_barcode_skip_package_scan", "boolean", "false"),
        ("hlv_barcode_skip_product_scan", "boolean", "false"),
        ("hlv_barcode_receive_require_detail_scan", "boolean", "false"),
        ("hlv_barcode_receive_skip_package_scan", "boolean", "false"),
        ("hlv_barcode_receive_skip_product_scan", "boolean", "false"),
        ("hlv_barcode_return_require_detail_scan", "boolean", "false"),
        ("hlv_barcode_return_skip_package_scan", "boolean", "false"),
        ("hlv_barcode_return_skip_product_scan", "boolean", "false"),
    ]
    for col, col_type, default in company_columns:
        cr.execute(
            f"ALTER TABLE res_company ADD COLUMN IF NOT EXISTS {col} {col_type} DEFAULT {default};"
        )

    # === stock_picking: shipper receive/return tracking fields ===
    cr.execute("ALTER TABLE stock_picking ADD COLUMN IF NOT EXISTS shipper_received boolean DEFAULT false;")
    cr.execute("ALTER TABLE stock_picking ADD COLUMN IF NOT EXISTS shipper_receive_time timestamp without time zone;")
    cr.execute("ALTER TABLE stock_picking ADD COLUMN IF NOT EXISTS shipper_received_by integer;")
    cr.execute("ALTER TABLE stock_picking ADD COLUMN IF NOT EXISTS shipper_returned boolean DEFAULT false;")
    cr.execute("ALTER TABLE stock_picking ADD COLUMN IF NOT EXISTS shipper_return_time timestamp without time zone;")
    cr.execute("ALTER TABLE stock_picking ADD COLUMN IF NOT EXISTS shipper_return_reason varchar;")
