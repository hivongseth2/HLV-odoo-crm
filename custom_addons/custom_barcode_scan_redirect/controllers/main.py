
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
            
            _logger.info(f"[SCAN] Barcode: {picking.picking_type_id.code}")
            
            if picking.picking_type_id.code == 'internal':  #  nếu  có phân loại riêng cho PACK thì đổi lại
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'message': f"✅ Phiếu {picking.name} đã hoàn tất!",
                        'type': 'info',
                        'sticky': False,
                    }
                }
            
            
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
        _logger.info(f"[ACTION] Gửi barcode_action cho phiếu: {picking.name} | Picking Type: {picking.picking_type_id.name}")
        # ❌ Nếu loại phiếu không phải là 'outgoing' hoặc 'pick' thì không mở barcode
        if picking.picking_type_id.code not in ['out', 'pick']:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': f"Phiếu {picking.name} không thuộc loại Pick hoặc Out. Không thể mở giao diện barcode.",
                    'type': 'warning',
                    'sticky': False,
                }
            }

        # ✅ Nếu qua được tất cả điều kiện thì mở giao diện barcode như thường
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
        origin_pick = request.env['stock.picking'].sudo().search([
                ('group_id', '=', picking.group_id.id),
                ('picking_type_id.sequence_code', 'like', 'PICK'),  # hoặc theo name như 'HCM: Pick'
                ('id', '!=', picking.id)
            ], limit=1)

        return request.render("custom_barcode_scan_redirect.pack_scan_template", {
            'picking': picking,
            'lines': lines,
            # 'origin_pick_name': picking.group_id and picking.group_id.name or ''
            'origin_pick_name': origin_pick.name if origin_pick else '',

        })



    @http.route('/pack_scan/scan_item', type='json', auth='user')
    def scan_pack_item(self, **kwargs):
        picking_id = kwargs.get("picking_id")
        barcode = kwargs.get("barcode")
        delta = int(kwargs.get("delta", 1))
        line_id = kwargs.get("line_id")
        _logger = logging.getLogger(__name__)

        picking = request.env['stock.picking'].sudo().browse(picking_id)
        moves = picking.move_ids_without_package.filtered(lambda m: m.product_id.barcode == barcode)

        if not moves:
            return {"error": "❌ Mã sản phẩm không khớp trong phiếu!"}

        total_required = sum(m.product_uom_qty for m in moves)
        total_done = sum(sum(ml.qty_done for ml in m.move_line_ids) for m in moves)

        if delta > 0 and total_done >= total_required:
            return {"error": "⚠️ Sản phẩm này đã được quét đủ!"}

        updated_lines = []
        

        for move in moves:
            if line_id:
                target_ml = move.move_line_ids.filtered(lambda ml: ml.id == int(line_id))
                if target_ml:
                    ml = target_ml[0]
                    # current_qty = ml.qty_done
                    ml = ml.sudo().browse(ml.id)  # Ép load lại bản mới
                    current_qty = ml.qty_done
                    total_done = sum(l.qty_done for l in move.move_line_ids)
                    remain_qty = max(0, move.product_uom_qty - total_done)
                    
                    _logger.info(f"[SCAN] 📦 Product: {move.product_id.display_name}")
                    _logger.info(f"[SCAN] 🆔 line_id: {ml.id}, total_done: {total_done}, required: {move.product_uom_qty}")
                    _logger.info(f"[SCAN] ➕ delta: {delta}, remain_qty: {remain_qty}")
                    _logger.info(f"[SCAN] ➕ curren_quantity: {current_qty}")

                    if delta > 0 and remain_qty > 0:
                        add_qty = min(delta, remain_qty)
                        new_qty = current_qty + add_qty
                        ml.write({'qty_done': new_qty})
                        new_total_done = total_done - current_qty + new_qty
                        _logger.info(f"[SCAN] ✅ Added {add_qty}, new_qty: {new_qty}, new_total_done: {new_total_done}")
                        updated_lines.append({
                            "line_id": ml.id,
                            "product": move.product_id.display_name,
                            "done_qty": new_total_done,
                            "required_qty": move.product_uom_qty
                        })
                        break
                    elif delta < 0 and total_done > 0:
                        reduce_qty = min(abs(delta), current_qty)
                        # new_qty = current_qty - reduce_qty
                        # new_qty = total_done  -1
                        new_qty = current_qty - reduce_qty
                        ml.write({'qty_done': new_qty})
                        new_total_done = total_done - current_qty + new_qty
                        _logger.info(f"[SCAN] ✅ Reduced {reduce_qty}, new_qty: {new_qty} , new_qty_done:{new_total_done}")
                        updated_lines.append({
                            "line_id": ml.id,
                            "product": move.product_id.display_name,
                            "done_qty": new_total_done ,
                            "required_qty": move.product_uom_qty
                        })
                        break


        if not updated_lines:
            return {"error": "⚠️ Không có dòng nào để cập nhật!"}

        return {"scanned": updated_lines}



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


