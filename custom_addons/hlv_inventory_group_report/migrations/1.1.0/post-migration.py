def migrate(cr, version):
    cr.execute("SELECT to_regclass('hlv_report_group_product_rel')")
    if not cr.fetchone()[0]:
        return
    cr.execute(
        """
        INSERT INTO hlv_product_report_group_line
            (group_id, product_id, created_at, updated_at, create_uid, write_uid, create_date, write_date)
        SELECT DISTINCT
            rel.group_id,
            rel.product_id,
            COALESCE(grp.write_date, grp.create_date, NOW() AT TIME ZONE 'UTC'),
            COALESCE(grp.write_date, grp.create_date, NOW() AT TIME ZONE 'UTC'),
            COALESCE(grp.create_uid, 1),
            COALESCE(grp.write_uid, grp.create_uid, 1),
            COALESCE(grp.write_date, grp.create_date, NOW() AT TIME ZONE 'UTC'),
            COALESCE(grp.write_date, grp.create_date, NOW() AT TIME ZONE 'UTC')
        FROM hlv_report_group_product_rel rel
        JOIN hlv_product_report_group grp ON grp.id = rel.group_id
        JOIN product_product prod ON prod.id = rel.product_id
        WHERE NOT EXISTS (
            SELECT 1
            FROM hlv_product_report_group_line line
            WHERE line.group_id = rel.group_id
              AND line.product_id = rel.product_id
        )
        """
    )
    cr.execute(
        """
        UPDATE hlv_product_report_group grp
        SET product_count = counts.product_count
        FROM (
            SELECT group_id, COUNT(*) AS product_count
            FROM hlv_product_report_group_line
            GROUP BY group_id
        ) counts
        WHERE counts.group_id = grp.id
        """
    )
