# === controllers/main.py ===
from odoo import http
from odoo.http import request

class CustomBarcodeScanController(http.Controller):

    @http.route('/custom_barcode_scan/ui/scan', type='json', auth='user')
    def scan_ui_api(self, barcode):
        Picking = request.env['stock.picking'].sudo()
        picking = Picking.search([('name', '=', barcode)], limit=1)

        if not picking:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': f"Mã '{barcode}' không tồn tại!",
                    'type': 'danger',
                    'sticky': False,
                }
            }

        # Nếu phiếu đã done và có group liên kết
        if picking.state == 'done' and picking.group_id:
            next_picking = Picking.search([
                ('group_id', '=', picking.group_id.id),
                ('id', '!=', picking.id),
                ('state', 'in', ['confirmed', 'assigned', 'waiting'])
            ], limit=1)
            if next_picking:
                return next_picking.action_view()
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'message': "Không tìm thấy phiếu liên kết tiếp theo!",
                        'type': 'warning',
                        'sticky': False,
                    }
                }

        # Nếu phiếu chưa done, mở luôn
        return picking.action_view()