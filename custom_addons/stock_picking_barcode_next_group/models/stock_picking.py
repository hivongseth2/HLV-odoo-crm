from odoo import models

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _get_barcode_data(self, barcode):
        record = self.search([('name', '=', barcode)], limit=1)
        if record and record.state == 'done' and record.group_id:
            next_picking = self.search([
                ('group_id', '=', record.group_id.id),
                ('id', '!=', record.id),
                ('state', 'not in', ['done', 'cancel']),
            ], order='scheduled_date asc', limit=1)
            if next_picking:
                record = next_picking
        return super()._get_barcode_data(record.name if record else barcode)
