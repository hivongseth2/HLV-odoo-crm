
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

        if picking.state == 'done' and picking.group_id:
            next_picking = Picking.search([
                ('group_id', '=', picking.group_id.id),
                ('id', '!=', picking.id),
                ('state', 'in', ['confirmed', 'assigned', 'waiting'])
            ], limit=1)
            if next_picking:
                return {
                    'type': 'ir.actions.act_url',
                    'url': f"/custom_barcode_scan/pack_view/{next_picking.id}",
                    'target': 'self',
                }

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': "Không tìm thấy phiếu liên kết tiếp theo!",
                    'type': 'warning',
                    'sticky': False,
                }
            }

        return self._get_barcode_action(picking.id)

    def _get_barcode_action(self, picking_id):
        _logger = logging.getLogger(__name__)
        Picking = request.env['stock.picking'].sudo()
        picking = Picking.browse(picking_id)

        if not picking.exists():
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': f"Phiếu #{picking_id} không tồn tại.",
                    'type': 'danger',
                    'sticky': False,
                }
            }

        if not picking.picking_type_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': "Phiếu không có loại chuyển kho, không thể mở giao diện barcode.",
                    'type': 'danger',
                    'sticky': False,
                }
            }

        action = request.env.ref('stock_barcode.stock_barcode_picking_client_action').sudo().read()[0]

        action.update({
            'context': {
                'active_id': picking.id,
                'default_picking_type_id': picking.picking_type_id.id,
                'res_model': 'stock.picking',
                'res_id': picking.id,
            }
        })

        _logger.info(f"[ACTION] Gửi barcode_action cho phiếu: {picking.name} | Picking Type: {picking.picking_type_id.name}")
        return action

        
    @http.route('/custom_barcode_scan/pack_view/<int:picking_id>', type='http', auth='user')
    def view_pack_products(self, picking_id):
        _logger = logging.getLogger(__name__)
        _logger.info(f"🔍 Đang vào pack_view với ID: {picking_id}")

        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            _logger.error("❌ Không tìm thấy phiếu pack!")
            return request.not_found()

        # lines = picking.move_lines.filtered(lambda m: m.product_id)
        lines = picking.move_ids_without_package.filtered(lambda m: m.product_id)

        _logger.info(f"📦 Tổng dòng move line có product: {len(lines)}")

        return request.render("custom_barcode_scan_redirect.pack_scan_template", {
            'picking': picking,
            'lines': lines,
        })

    @http.route('/pack_scan/scan_item', type='json', auth='user')
    def scan_pack_item(self, **kwargs):
        picking_id = kwargs.get("picking_id")
        barcode = kwargs.get("barcode")
        delta = int(kwargs.get("delta", 1))  # +1 hoặc -1

        picking = request.env['stock.picking'].sudo().browse(picking_id)
        moves = picking.move_ids_without_package.filtered(lambda l: l.product_id.barcode == barcode)

        if not moves:
            return {"error": "❌ Mã sản phẩm không khớp trong phiếu!"}

        scanned = []
        for move in moves:
            required_qty = move.product_uom_qty
            move_line = move.move_line_ids and move.move_line_ids[0]

            if move_line:
                new_qty = move_line.qty_done + delta
                new_qty = max(0, min(new_qty, required_qty))
                move_line.qty_done = new_qty
            else:
                if delta > 0:
                    request.env['stock.move.line'].sudo().create({
                        'picking_id': picking.id,
                        'move_id': move.id,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_uom.id,
                        'qty_done': min(delta, required_qty),
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                    })

            total_done = sum(ml.qty_done for ml in move.move_line_ids)

            scanned.append({
                "product": move.product_id.display_name,
                "done_qty": total_done,
                "required_qty": required_qty
            })

        return {"scanned": scanned}


    
    @http.route('/pack_scan/complete_picking', type='json', auth='user')
    def complete_pack_picking(self, **kwargs):
        picking_id = kwargs.get("picking_id")
        picking = request.env['stock.picking'].sudo().browse(picking_id)

        if not picking.exists():
            return {"error": "Phiếu không tồn tại."}
        if picking.state not in ['assigned', 'confirmed', 'in_progress']:
            return {"error": f"Phiếu không ở trạng thái cho phép xác nhận (hiện tại: {picking.state})."}
        for move in picking.move_ids_without_package:
                total_done = sum(ml.qty_done for ml in move.move_line_ids)
                if total_done < move.product_uom_qty:
                    return {
                        "error": f"⚠️ Sản phẩm '{move.product_id.display_name}' chưa đủ số lượng!"
                    }
        try:
            picking.button_validate()
            return {"success": True, "message": f"✅ Phiếu {picking.name} đã được xác nhận!"}
        except Exception as e:
            return {"error": str(e)}


