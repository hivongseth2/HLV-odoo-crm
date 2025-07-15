from odoo import models, api

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    @api.model
    def get_barcode_view_state(self, barcode):
        picking = self.search([('name', '=', barcode)], limit=1)

        if not picking:
            return super().get_barcode_view_state(barcode)

        if picking.state == 'done' and picking.group_id:
            next_picking = self.search([
                ('group_id', '=', picking.group_id.id),
                ('state', 'not in', ['done', 'cancel']),
                ('id', '!=', picking.id)
            ], order='scheduled_date asc', limit=1)

            if next_picking:
                return next_picking.get_barcode_view_state(next_picking.name)

        # Mặc định fallback
        return super().get_barcode_view_state(barcode)
