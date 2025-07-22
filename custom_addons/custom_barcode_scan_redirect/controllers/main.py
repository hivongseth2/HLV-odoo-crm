from odoo import http
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)
# 222
class CustomBarcodeScanController(http.Controller):

    @http.route(['/custom_barcode_scan/ui'], type='http', auth='user')
    def scan_ui(self):
        return request.render("custom_barcode_scan_redirect.scan_ui_template")

    @http.route('/custom_barcode_scan/ui/scan', type='json', auth='user', csrf=False)
    def scan_ui_api(self, **kwargs):
        barcode = kwargs.get("barcode")
        _logger.info(f"[SCAN] Barcode: {barcode}")

        Picking = request.env['stock.picking'].sudo()
        current_picking = Picking.search([('name', '=', barcode)], limit=1)

        if not current_picking:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': f"❌ Không tìm thấy phiếu với mã: {barcode}",
                    'type': 'danger',
                    'sticky': False,
                }
            }

        # Nếu phiếu đã done → tìm phiếu tiếp theo trong cùng group (chưa done)
        if current_picking.state == 'done' and current_picking.group_id:
            next_picking = Picking.search([
                ('group_id', '=', current_picking.group_id.id),
                ('id', '!=', current_picking.id),
                ('state', 'not in', ['done', 'cancel']),
            ], order='scheduled_date asc', limit=1)

            if next_picking:
                _logger.info(f"[SCAN] Phiếu đã hoàn tất. Nhảy sang phiếu kế tiếp: {next_picking.name}")
                current_picking = next_picking
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'message': "✅ Phiếu đã hoàn tất và không còn phiếu tiếp theo trong nhóm!",
                        'type': 'success',
                        'sticky': False,
                    }
                }

        try:
            action_id = request.env.ref("stock_barcode.stock_barcode_picking_client_action").id
            return {
                "action_id": action_id,
                "context": {
                    "active_model": "stock.picking",
                    "active_id": current_picking.id,
                    "active_ids": [current_picking.id],
                }
            }

        except Exception as e:
            _logger.exception("🔥 Lỗi khi lấy action stock_barcode_picking_client_action")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': f"🚨 Lỗi khi mở giao diện barcode: {str(e)}",
                    'type': 'danger',
                    'sticky': False,
                }
            }
