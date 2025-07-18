from odoo import models, api

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    @api.model
    def _get_barcode_data(self, barcode):
        picking = self.search(['|', ('name', '=', barcode), ('barcode', '=', barcode)], limit=1)

        if picking and picking.state == 'done' and picking.group_id:
            next_picking = self.search([
                ('group_id', '=', picking.group_id.id),
                ('id', '!=', picking.id),
                ('state', 'not in', ['done', 'cancel']),
            ], order='scheduled_date asc', limit=1)
            if next_picking:
                picking = next_picking

        return super()._get_barcode_data(picking.name if picking else barcode)
