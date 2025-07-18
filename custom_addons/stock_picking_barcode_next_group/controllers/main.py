from odoo import http
from odoo.http import request

class StockBarcodeNextGroupController(http.Controller):

    @http.route('/stock_barcode/scan_from_main_menu', type='json', auth='user')
    def scan_from_main_menu(self, barcode=None):
        picking = request.env['stock.picking'].sudo().search([('name', '=', barcode)], limit=1)
        if picking and picking.state == 'done' and picking.group_id:
            next_picking = request.env['stock.picking'].sudo().search([
                ('group_id', '=', picking.group_id.id),
                ('id', '!=', picking.id),
                ('state', 'not in', ['done', 'cancel']),
            ], order='scheduled_date asc', limit=1)
            if next_picking:
                picking = next_picking
        if picking:
            return {
                'res_model': 'stock.picking',
                'res_id': picking.id,
                'type': 'picking',
            }
        return {'type': 'error', 'message': 'Phiếu không tồn tại'}
