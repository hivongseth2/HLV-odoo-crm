from odoo import http
from odoo.http import request

class StockBarcodePatchedController(http.Controller):

    @http.route('/stock_barcode/scan_from_main_menu', type='json', auth='user')
    def scan_from_main_menu(self, barcode):
        Picking = request.env['stock.picking'].sudo()
        record = Picking.search([('name', '=', barcode)], limit=1)

        if record and record.state == 'done' and record.group_id:
            next_picking = Picking.search([
                ('group_id', '=', record.group_id.id),
                ('id', '!=', record.id),
                ('state', 'not in', ['done', 'cancel']),
            ], order='scheduled_date asc', limit=1)
            if next_picking:
                record = next_picking

        # simulate original behavior
        return request.env['stock.picking']._get_barcode_data(record.name if record else barcode)
