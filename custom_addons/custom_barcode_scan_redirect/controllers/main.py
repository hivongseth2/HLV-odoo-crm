from odoo import http
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)

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
            return {
                'status': 'ok',
                'picking': {
                    'name': current_picking.name,
                    'state': current_picking.state,
                    'scheduled_date': str(current_picking.scheduled_date),
                    'partner': current_picking.partner_id.name,
                    'products': [{
                        'product_name': move.product_id.display_name,
                        'qty_done': move.quantity_done,
                        'qty_total': move.product_uom_qty,
                    } for move in current_picking.move_ids_without_package]
                }
            }
        except Exception as e:
            _logger.exception("🔥 Lỗi khi xử lý phiếu")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': f"🚨 Lỗi: {str(e)}",
                    'type': 'danger',
                    'sticky': False,
                }
            }
