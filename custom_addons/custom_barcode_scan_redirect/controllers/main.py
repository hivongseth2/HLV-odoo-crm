
from odoo import http
from odoo.http import request
import json

class CustomPackScanController(http.Controller):

    @http.route('/custom_barcode_scan/pack_view/<int:picking_id>', type='http', auth='user')
    def view_pack_products(self, picking_id):
        picking = request.env['stock.picking'].sudo().browse(picking_id)
        lines = picking.move_lines.filtered(lambda m: m.product_id)
        return request.render("custom_barcode_pack_scan.pack_scan_template", {
            'picking': picking,
            'lines': lines,
        })

    @http.route('/pack_scan/scan_item', type='json', auth='user')
    def scan_pack_item(self, **kwargs):
        picking_id = kwargs.get("picking_id")
        barcode = kwargs.get("barcode")

        picking = request.env['stock.picking'].sudo().browse(picking_id)
        lines = picking.move_lines.filtered(lambda l: l.product_id.barcode == barcode)

        if not lines:
            return {"error": "Mã sản phẩm không khớp trong phiếu!"}

        scanned = []
        for line in lines:
            scanned.append({
                "product": line.product_id.display_name,
                "done_qty": line.qty_done + 1 if line.qty_done < line.product_uom_qty else line.qty_done,
                "required_qty": line.product_uom_qty
            })

        return {"scanned": scanned}
