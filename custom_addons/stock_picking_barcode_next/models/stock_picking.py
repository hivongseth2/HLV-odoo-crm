from odoo import models

class StockPicking(models.Model):
    _inherit = "stock.picking"

    def get_next_picking_by_group(self):
        self.ensure_one()
        group_id = self.env.context.get("group_id")
        if not group_id:
            return {}

        next_picking = self.search([
            ("group_id", "=", group_id),
            ("id", "!=", self.id),
            ("state", "not in", ["done", "cancel"]),
        ], order="scheduled_date asc", limit=1)

        return {"next_picking_id": next_picking.id if next_picking else False}
