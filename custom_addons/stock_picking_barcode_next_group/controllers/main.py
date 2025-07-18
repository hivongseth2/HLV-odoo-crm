from odoo import http
from odoo.http import request
from odoo.addons.stock_barcode.controllers.main import StockBarcodeController

class StockBarcodeControllerOverride(StockBarcodeController):
    @http.route('/stock_barcode/scan_from_main_menu', type='json', auth='user', methods=['POST'])
    def scan_from_main_menu(self, barcode, **kw):
        """Override of stock_barcode scan_from_main_menu to skip done pickings."""
        # Try to find a stock.picking matching the scanned barcode
        Picking = request.env['stock.picking']
        picking = Picking.search(['|', ('barcode', '=', barcode), ('name', '=', barcode)], limit=1)
        if picking:  # A picking record matches the scanned code
            if picking.state == 'done':
                # If picking is done, find another picking in the same group that is not done or cancelled
                alt_picking = Picking.search([
                    ('group_id', '=', picking.group_id.id),
                    ('state', 'not in', ['done', 'cancel']),
                    ('id', '!=', picking.id)
                ], order='id', limit=1)
                if alt_picking:
                    # If found a pending picking in same group, redirect to that one
                    return super(StockBarcodeControllerOverride, self).scan_from_main_menu(alt_picking.name, **kw)
            # If picking is not done, or no alternate found, fall back to original picking
            # (It will be opened normally – possibly in read-only if done with no alternates)
            return super(StockBarcodeControllerOverride, self).scan_from_main_menu(barcode, **kw)
        # If the scanned barcode isn't a picking, use the original logic (products, locations, etc.)
        return super(StockBarcodeControllerOverride, self).scan_from_main_menu(barcode, **kw)
