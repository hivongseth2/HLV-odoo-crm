"""Synchronize existing discrepancy quantities with their inventory lines."""


def migrate(cr, version):
    cr.execute(
        """
        UPDATE inventory_discrepancy AS discrepancy
           SET difference = line.scanned_qty - line.theoretical_qty
          FROM inventory_check_line AS line
         WHERE discrepancy.line_id = line.id
           AND discrepancy.difference IS DISTINCT FROM
               (line.scanned_qty - line.theoretical_qty)
        """
    )
