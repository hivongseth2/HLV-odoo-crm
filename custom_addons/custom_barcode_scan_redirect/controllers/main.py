from odoo import http
from odoo.http import request


class CustomBarcodeScanController(http.Controller):

    @http.route('/custom_barcode_scan', type='json', auth='user')
    def custom_barcode_scan(self, barcode):
        StockPicking = request.env['stock.picking']
        picking = StockPicking.search([('name', '=', barcode)], limit=1)

        if picking and picking.state == 'done' and picking.group_id:
            next_picking = StockPicking.search([
                ('group_id', '=', picking.group_id.id),
                ('state', 'not in', ['done', 'cancel']),
                ('id', '!=', picking.id)
            ], order='scheduled_date asc', limit=1)

            if next_picking:
                return next_picking.get_barcode_view_state(next_picking.name)

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Thông báo",
                    "message": "Tất cả phiếu trong quy trình đã hoàn thành.",
                    "sticky": False,
                }
            }

        if picking:
            return picking.get_barcode_view_state(picking.name)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Không tìm thấy phiếu",
                "message": f"Không tìm thấy phiếu với mã: {barcode}",
                "sticky": False,
            }
        }