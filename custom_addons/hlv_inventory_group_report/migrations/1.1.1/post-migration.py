import json


AVG_PREFIX = "hlv_inventory_group_report.manual_avg_cost."
LAYERS_PREFIX = "hlv_inventory_group_report.manual_layer_amounts."
AVG_LIKE = AVG_PREFIX.replace("_", r"\_") + "%"
LAYERS_LIKE = LAYERS_PREFIX.replace("_", r"\_") + "%"


def _to_int_suffix(key, prefix):
    try:
        return int(key[len(prefix):])
    except (TypeError, ValueError):
        return None


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def migrate(cr, version):
    cr.execute(
        """
        ALTER TABLE product_product
            ADD COLUMN IF NOT EXISTS hlv_manual_avg_cost_enabled boolean,
            ADD COLUMN IF NOT EXISTS hlv_manual_avg_cost double precision
        """
    )
    cr.execute(
        """
        ALTER TABLE purchase_order_line
            ADD COLUMN IF NOT EXISTS hlv_manual_cost_total_enabled boolean,
            ADD COLUMN IF NOT EXISTS hlv_manual_cost_total double precision
        """
    )

    cr.execute(
        """
        SELECT key, value
        FROM ir_config_parameter
        WHERE key LIKE %s ESCAPE '\\'
           OR key LIKE %s ESCAPE '\\'
        """,
        (AVG_LIKE, LAYERS_LIKE),
    )
    params = cr.fetchall()

    for key, value in params:
        if key.startswith(AVG_PREFIX):
            product_id = _to_int_suffix(key, AVG_PREFIX)
            avg_cost = _to_float(value)
            if product_id and avg_cost is not None:
                cr.execute(
                    """
                    UPDATE product_product
                    SET hlv_manual_avg_cost_enabled = TRUE,
                        hlv_manual_avg_cost = %s
                    WHERE id = %s
                    """,
                    (avg_cost, product_id),
                )
            continue

        if key.startswith(LAYERS_PREFIX):
            try:
                layer_amounts = json.loads(value or "{}")
            except json.JSONDecodeError:
                layer_amounts = {}
            if not isinstance(layer_amounts, dict):
                continue
            for line_id_raw, amount_raw in layer_amounts.items():
                try:
                    line_id = int(line_id_raw)
                except (TypeError, ValueError):
                    continue
                amount = _to_float(amount_raw)
                if amount is None:
                    continue
                cr.execute(
                    """
                    UPDATE purchase_order_line
                    SET hlv_manual_cost_total_enabled = TRUE,
                        hlv_manual_cost_total = %s
                    WHERE id = %s
                    """,
                    (amount, line_id),
                )

    cr.execute(
        """
        DELETE FROM ir_config_parameter
        WHERE key LIKE %s ESCAPE '\\'
           OR key LIKE %s ESCAPE '\\'
        """,
        (AVG_LIKE, LAYERS_LIKE),
    )
