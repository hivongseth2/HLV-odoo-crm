from odoo import http
from odoo.http import request, route
from odoo.tools import html_escape


class CustomBarcodeScanController(http.Controller):

    @route(['/custom_barcode_scan/ui'], type='http', auth='user')
    def scan_ui(self):
        return request.render("custom_barcode_scan_redirect.scan_ui_template")

    @route(['/custom_barcode_scan/ui/scan'], type='json', auth='user')
    def scan_ui_api(self, barcode):
        domain = [('state', '!=', 'cancel'), ('name', '=', barcode)]
        picking = request.env['stock.picking'].sudo().search(domain, limit=1)
        if not picking:
            return {"type": "ir.actions.client", "tag": "display_notification",
                    "params": {"title": "Không tìm thấy phiếu", "message": html_escape(barcode), "type": "danger"}}
        if picking.state == 'done':
            next_pick = request.env['stock.picking'].sudo().search([
                ('group_id', '=', picking.group_id.id),
                ('state', 'not in', ['cancel', 'done']),
                ('id', '!=', picking.id)
            ], limit=1, order='id asc')
            if next_pick:
                return next_pick.get_barcode_action()
            return {"type": "ir.actions.client", "tag": "display_notification",
                    "params": {"title": "Đã hoàn thành", "message": "Không còn phiếu nào tiếp theo", "type": "success"}}
        return picking.get_barcode_action()
