
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
        
        _logger.info.debug(f"[SCAN] ➕ line_id: {line_id}, remain_qty: {moves}")

        for move in moves:
            sorted_lines = move.move_line_ids.sorted(key=lambda ml: ml.qty_done)

            # --- Nếu nhấn tay, ưu tiên line_id ---
            if line_id:
                target_ml = move.move_line_ids.filtered(lambda ml: ml.id == int(line_id))
                if target_ml:
                    ml = target_ml[0]
                    total_done = sum(m.qty_done for m in move.move_line_ids)
                    remain_qty = move.product_uom_qty - total_done
                    _logger.info(f"[SCAN] 📦 Product: {move.product_id.display_name}")
                    _logger.info(f"[SCAN] 🆔 line_id: {ml.id}, current_qty_done: {ml.qty_done}, total_done: {total_done}, required: {move.product_uom_qty}")
                    _logger.info(f"[SCAN] ➕ delta: {delta}, remain_qty: {remain_qty}")
                    # if delta > 0 and remain_qty > 0:
                    #     add_qty = min(delta, remain_qty)
                    #     new_qty = ml.qty_done + add_qty
                    #     ml.write({'qty_done': new_qty})
                    #     ml = ml.sudo().browse(ml.id)  # Reload lại để lấy giá trị mới
                    #     _logger.debug(f"[SCAN] ✅ Adding qty: {add_qty} → new_qty_done: {new_qty}")
                    #     _logger.debug(f"[SCAN]  ml: {ml}")


                    # elif delta < 0 and ml.qty_done > 0:
                    #     new_qty = max(0, ml.qty_done + delta)
                    #     ml.write({'qty_done': new_qty})
                    #     ml = ml.sudo().browse(ml.id)
                    #     _logger.debug(f"[SCAN] ✅ Adding qty:  → delta < 0 qty>0: {new_qty}")
                    #     _logger.debug(f"[SCAN]  ml: {ml}")
                        


                    # updated_lines.append({
                    #     "line_id": ml.id,
                    #     "product": move.product_id.display_name,
                    #     "done_qty":new_qty,  
                    #     "required_qty": move.product_uom_qty
                    # })
                    # break
                    
                    if delta > 0 and remain_qty > 0:
                        add_qty = min(delta, remain_qty)
                        new_qty = ml.qty_done + add_qty
                        ml.write({'qty_done': new_qty})
                        ml = ml.sudo().browse(ml.id)
                        _logger.info(f"[SCAN] ✅ Adding qty: {add_qty} → new_qty_done: {new_qty}")
                        _logger.info(f"[SCAN]  ml: {ml}")

                        updated_lines.append({
                            "line_id": ml.id,
                            "product": move.product_id.display_name,
                            "done_qty": new_qty,
                            "required_qty": move.product_uom_qty
                        })
                        break

                    elif delta < 0 and ml.qty_done > 0:
                        new_qty = max(0, ml.qty_done + delta)
                        ml.write({'qty_done': new_qty})
                        ml = ml.sudo().browse(ml.id)
                        _logger.info(f"[SCAN] ✅ Reducing qty: {delta} → new_qty_done: {new_qty}")
                        _logger.info(f"[SCAN]  ml: {ml}")

                        updated_lines.append({
                            "line_id": ml.id,
                            "product": move.product_id.display_name,
                            "done_qty": new_qty,
                            "required_qty": move.product_uom_qty
                        })
                        break


            # # --- Nếu scan barcode ---
            # if not line_id:
            #     if delta > 0:
            #         for ml in sorted_lines:
            #             total_done = sum(m.qty_done for m in move.move_line_ids)
            #             if total_done >= move.product_uom_qty:
            #                 break

            #             remaining = move.product_uom_qty - total_done
            #             add_qty = min(delta, remaining)
            #             new_qty = ml.qty_done + add_qty
            #             ml.write({'qty_done': new_qty})
            #             ml = ml.sudo().browse(ml.id)


            #             updated_lines.append({
            #                 "line_id": ml.id,
            #                 "product": move.product_id.display_name,
            #                 "done_qty": ml.qty_done,
            #                 "required_qty": move.product_uom_qty
            #             })
            #             return {"scanned": updated_lines}



            #         # Nếu không có dòng nào thì tạo mới
            #         new_ml = request.env['stock.move.line'].sudo().create({
            #             'picking_id': picking.id,
            #             'move_id': move.id,
            #             'product_id': move.product_id.id,
            #             'product_uom_id': move.product_uom.id,
            #             'qty_done': min(delta, move.product_uom_qty),
            #             'location_id': move.location_id.id,
            #             'location_dest_id': move.location_dest_id.id,
            #         })
            #         updated_lines.append({
            #             "line_id": new_ml.id,
            #             "product": move.product_id.display_name,
            #             "done_qty": new_ml.qty_done,
            #             "required_qty": move.product_uom_qty
            #         })
            #         return {"scanned": updated_lines}

            #     else:  # delta < 0
            #         # ✅ Trừ đúng dòng cuối có qty_done > 0
            #         for ml in reversed(sorted_lines):
            #             if ml.qty_done > 0:
            #                 ml.qty_done = max(0, ml.qty_done + delta)
            #                 updated_lines.append({
            #                     "line_id": ml.id,
            #                     "product": move.product_id.display_name,
            #                     "done_qty": ml.qty_done,
            #                     "required_qty": move.product_uom_qty
            #                 })
            #                 return {"scanned": updated_lines}

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


