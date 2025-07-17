from odoo import http
from odoo.http import request
import json

class CustomBarcodeScanController(http.Controller):

    @http.route('/custom_barcode_scan/ui', auth='user', website=True)
    def scan_ui_page(self, **kwargs):
        return request.render("custom_barcode_scan_redirect.scan_ui_template", {})

    @http.route('/custom_barcode_scan/ui/scan', type='json', auth='user', methods=['POST'])
    def scan_ui_api(self, **kwargs):
        barcode = kwargs.get("barcode")
        if not barcode:
            return {"error": "Barcode is missing"}
        picking = request.env["stock.picking"].sudo().search([("name", "=", barcode)], limit=1)
        if not picking:
            return {"error": "Không tìm thấy phiếu với mã: %s" % barcode}
        if picking.state == "done":
            next_pick = request.env["stock.picking"].sudo().search([
                ("state", "not in", ["done", "cancel"]),
                ("id", ">", picking.id)
            ], limit=1, order="id asc")
            if next_pick:
                return {
                    "type": "ir.actions.act_window",
                    "res_model": "stock.picking",
                    "res_id": next_pick.id,
                    "view_mode": "form",
                    "target": "current",
                }
            else:
                return {"warning": "Phiếu hiện tại đã hoàn tất và không còn phiếu kế tiếp."}
        return {
            "type": "ir.actions.act_window",
            "res_model": "stock.picking",
            "res_id": picking.id,
            "view_mode": "form",
            "target": "current",
        }