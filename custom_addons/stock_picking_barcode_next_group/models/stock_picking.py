
from odoo import models, api

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    @api.model
    def _get_record_by_barcode(self, barcode):
        record = self.search([('name', '=', barcode)], limit=1)
        if record and record.state == 'done' and record.group_id:
            next_picking = self.search([
                ('group_id', '=', record.group_id.id),
                ('id', '!=', record.id),
                ('state', 'not in', ['done', 'cancel']),
            ], order='scheduled_date asc', limit=1)
            return next_picking or record
        return record
