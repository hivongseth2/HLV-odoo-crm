from odoo import http
from odoo.http import request
from odoo.addons.stock_barcode.controllers.main import StockBarcodeController


class StockBarcodeControllerInherit(StockBarcodeController):

    @http.route(['/stock_barcode/get_barcode_view_state'], type='json', auth='user')
    def get_barcode_view_state(self, model_name, barcode):
        if model_name == 'stock.picking':
            picking = request.env['stock.picking'].search([('name', '=', barcode)], limit=1)
            if picking and picking.state == 'done' and picking.group_id:
                next_picking = request.env['stock.picking'].search([
                    ('group_id', '=', picking.group_id.id),
                    ('state', 'not in', ['done', 'cancel']),
                    ('id', '!=', picking.id)
                ], order='scheduled_date asc', limit=1)

                if next_picking:
                    return next_picking.get_barcode_view_state(next_picking.name)

        return super().get_barcode_view_state(model_name, barcode)