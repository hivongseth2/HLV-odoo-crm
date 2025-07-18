
from odoo.addons.stock_barcode.controllers.main import StockBarcodeController
from odoo.http import request

def patched_scan_from_main_menu(self, barcode):
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

    return request.env['stock.picking']._get_barcode_data(record.name if record else barcode)

StockBarcodeController.scan_from_main_menu = patched_scan_from_main_menu
