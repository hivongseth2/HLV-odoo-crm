from odoo import http
from odoo.http import request
import logging

class CustomBarcodeScanController(http.Controller):

    @http.route(['/custom_barcode_scan/ui'], type='http', auth='user')
    def scan_ui(self):
        return request.render("custom_barcode_scan_redirect.scan_ui_template")

    @http.route('/custom_barcode_scan/ui/scan', type='json', auth='user', csrf=False)
    def scan_ui_api(self, **kwargs):
        _logger = logging.getLogger(__name__)
        barcode = kwargs.get("barcode")
        _logger.info(f"[SCAN] Barcode: {barcode}")

        Picking = request.env['stock.picking'].sudo()
        picking = Picking.search([('name', '=', barcode)], limit=1)

        if not picking:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': f"Không tìm thấy phiếu với mã: {barcode}",
                    'type': 'danger',
                    'sticky': False,
                }
            }

        # Nếu phiếu đã done và có group => tìm phiếu tiếp theo
        if picking.state == 'done' and picking.group_id:
            next_picking = Picking.search([
                ('group_id', '=', picking.group_id.id),
                ('id', '!=', picking.id),
                ('state', 'in', ['confirmed', 'assigned', 'waiting'])
            ], limit=1)
            if next_picking:
                return self._get_barcode_action(next_picking.id)

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': "Không tìm thấy phiếu liên kết tiếp theo!",
                    'type': 'warning',
                    'sticky': False,
                }
            }

        # Nếu chưa done => mở view barcode của phiếu hiện tại
        return self._get_barcode_action(picking.id)

    def _get_barcode_action(self, picking_id):
        _logger = logging.getLogger(__name__)
        picking = request.env['stock.picking'].sudo().browse(picking_id)

        if not picking.exists() or not picking.picking_type_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': "Phiếu không hợp lệ hoặc thiếu loại chuyển kho.",
                    'type': 'danger',
                    'sticky': False,
                }
            }

        # Lấy action gốc nhưng chỉ giữ phần cần thiết
        action_id = request.env.ref('stock_barcode.stock_barcode_picking_client_action').id

        return {
            'type': 'ir.actions.client',
            'tag': 'stock_barcode_client_action',
            'res_model': 'stock.picking',
            'res_id': picking.id,
            'target': 'fullscreen',
            'context': {
                'active_id': picking.id,
                'default_picking_type_id': picking.picking_type_id.id,
            },
            # 👇 Quan trọng! Truyền ID để frontend gọi lại load action chuẩn
            'id': action_id
        }
