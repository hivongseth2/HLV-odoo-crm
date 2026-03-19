# -*- coding: utf-8 -*-
"""Core pack scanning routes: scan_item, complete_picking, check_and_print_label."""
from odoo import http
from odoo.http import request
import logging

from ._shared import get_ml_demand

_logger = logging.getLogger(__name__)


class PackScanController(http.Controller):

    @http.route('/pack_scan/scan_item', type='json', auth='user')
    def scan_pack_item(self, **kwargs):
        picking_id = kwargs.get("picking_id")
        barcode = kwargs.get("barcode")
        delta = float(kwargs.get("delta", 1))
        line_id = kwargs.get("line_id")
        move_id = kwargs.get("move_id")
        _logger.info(f"SCAN_ITEM START: barcode={barcode}, delta={delta}, line_id={line_id}, move_id={move_id}")
        picking = request.env['stock.picking'].sudo().browse(picking_id)
        # Tìm move dựa trên barcode
        moves = picking.move_ids.filtered(lambda m: m.product_id.barcode == barcode)

        # Sort moves by Size (Demand) DESCENDING to prevent "Small Move First" overflow
        moves = moves.sorted(key=lambda m: (m.product_uom_qty, m.id), reverse=True)

        if not moves:
            return {"error": "❌ Mã sản phẩm không khớp trong phiếu!"}
        # Tính tổng quát để check xem đã đủ hết chưa
        total_required = sum(m.product_uom_qty for m in moves)
        total_done = sum(sum(ml.qty_done for ml in m.move_line_ids) for m in moves)
        if delta > 0 and total_done >= total_required:
            return {"error": "⚠️ Sản phẩm này đã được quét đủ!"}
        updated_lines = []

        # Chặn quét nếu kho không đủ hàng
        product = moves[0].product_id
        loc_id = moves[0].location_id.id
        if product.type in ['product', 'consu'] and product.with_context(location=loc_id).qty_available <= 0:
            return {"error": f"⚠️ Sản phẩm {product.display_name} hiện không có tồn kho thực tế tại {moves[0].location_id.display_name}!"}

        # --- Tìm target move_line ---
        target_ml = self._resolve_target_line(picking, moves, line_id, move_id, delta)

        # Nếu chưa xác định được target_ml, tự động tìm dòng phù hợp
        if not target_ml:
            target_ml = self._find_auto_target(picking, moves, move_id, delta)

        # Fallback cho delta < 0: báo lỗi chính xác
        if not target_ml and delta < 0:
            has_packed_items = False
            for move in moves:
                for ml in move.move_line_ids:
                    if ml.qty_done > 0 and ml.result_package_id:
                        has_packed_items = True
                        break
            if has_packed_items:
                return {"error": "⚠️ Sản phẩm nằm trong kiện. Vui lòng vào chi tiết kiện để xóa!"}

        # --- THỰC HIỆN CẬP NHẬT ---
        if target_ml:
            result = self._apply_qty_update(target_ml, delta)
            if isinstance(result, dict) and 'error' in result:
                return result
            updated_lines = result

        _logger.info(f"Returning updated_lines: {len(updated_lines)}")
        if not updated_lines:
            return {"error": "⚠️ Không tìm thấy dòng sản phẩm phù hợp để cập nhật! Có thể sản phẩm đã được đóng gói, vui lòng chỉnh sửa trong giao diện đóng gói!"}
        return {"scanned": updated_lines}

    # ---------- Private helpers for scan_pack_item ----------

    def _resolve_target_line(self, picking, moves, line_id, move_id, delta):
        """Resolve target move_line from FE-provided line_id/move_id. Returns None if not resolved."""
        target_ml = None
        if line_id:
            try:
                target_ml = request.env['stock.move.line'].sudo().browse(int(line_id))
                if not target_ml.exists():
                    target_ml = None
            except:
                target_ml = None

        target_move_from_fe = None
        if move_id:
            try:
                target_move_from_fe = request.env['stock.move'].sudo().browse(int(move_id))
                if not target_move_from_fe.exists() or target_move_from_fe.picking_id.id != picking.id:
                    target_move_from_fe = None
            except:
                target_move_from_fe = None

        if not target_ml:
            return None

        # Smart-redirect logic: tìm dòng tốt nhất cho sản phẩm
        is_target_packed = target_ml.result_package_id or target_ml.package_id
        target_res = getattr(target_ml, 'reserved_qty', 0) or getattr(target_ml, 'reserved_uom_qty', 0) or 0

        if not is_target_packed or (target_res == 0 and target_ml.qty_done > 0):
            if target_move_from_fe:
                all_product_mls = target_move_from_fe.move_line_ids.filtered(
                    lambda l: l.product_id.id == target_ml.product_id.id
                )
            else:
                all_product_mls = picking.move_line_ids.filtered(
                    lambda l: l.product_id.id == target_ml.product_id.id
                )

            def get_prio(l):
                is_pkg = bool(l.package_id or l.result_package_id)
                res = get_ml_demand(l)
                is_empty = (l.qty_done == 0)
                return (is_pkg, res > 0, is_empty, -l.id)

            sorted_mls = sorted(all_product_mls, key=get_prio, reverse=True)

            candidate = None
            # Bước 1: Tìm dòng HÀNG LẺ (ưu tiên loose trước)
            if not candidate:
                for l in sorted_mls:
                    is_pkg = bool(l.package_id or l.result_package_id)
                    if not is_pkg:
                        candidate = l
                        _logger.info(f"REDIRECT FOUND (Loose Line Match): ML {l.id} | No Package")
                        break

            # Bước 2: Fallback — tìm dòng PACKAGE còn chỗ (nếu không có loose)
            if not candidate:
                for l in sorted_mls:
                    is_pkg = bool(l.package_id or l.result_package_id)
                    res = get_ml_demand(l)
                    if is_pkg:
                        if (res > 0 and l.qty_done < res) or (res == 0 and l.qty_done == 0):
                            candidate = l
                            _logger.info(f"REDIRECT FOUND (Package Match): ML {l.id} | Package: {l.package_id.name or l.result_package_id.name}")
                            break

            if candidate:
                _logger.info(f"REDIRECT EXECUTE: ML {target_ml.id} -> ML {candidate.id}")
                target_ml = candidate

        if delta > 0:
            mv = target_ml.move_id
            mv_done = sum(l.qty_done for l in mv.move_line_ids)
            reserved_qty = get_ml_demand(target_ml)
            is_packed = target_ml.result_package_id or target_ml.package_id

            if mv_done >= mv.product_uom_qty:
                _logger.info(f"Target line {target_ml.id} belongs to FULL Move {mv.id} ({mv_done}/{mv.product_uom_qty}). Switching to find another.")
                target_ml = None
            elif is_packed and reserved_qty > 0 and target_ml.qty_done >= reserved_qty:
                _logger.info(f"Target line {target_ml.id} is packed ({is_packed.name}) and reaches Reserved Qty ({reserved_qty}). Skipping.")
                target_ml = None
            elif target_ml.result_package_id and reserved_qty == 0 and target_ml.qty_done > 0:
                _logger.info(f"Target line {target_ml.id} is already fully packed with no reserved qty. Skipping.")
                target_ml = None
            else:
                _logger.info(f"Target line {target_ml.id} is valid (Space: {target_ml.qty_done}/{reserved_qty} | Move: {mv_done}/{mv.product_uom_qty}). Keeping it.")

        return target_ml

    def _find_auto_target(self, picking, moves, move_id, delta):
        """Auto-find a target move_line when FE didn't specify one or it was invalid."""
        target_move_from_fe = None
        if move_id:
            try:
                target_move_from_fe = request.env['stock.move'].sudo().browse(int(move_id))
                if not target_move_from_fe.exists() or target_move_from_fe.picking_id.id != picking.id:
                    target_move_from_fe = None
            except:
                target_move_from_fe = None

        scoped_moves = moves
        if target_move_from_fe and target_move_from_fe in moves:
            scoped_moves = target_move_from_fe

        if delta > 0:
            return self._find_auto_target_add(picking, scoped_moves)
        elif delta < 0:
            return self._find_auto_target_subtract(scoped_moves)
        return None

    def _find_auto_target_add(self, picking, scoped_moves):
        """Find a move_line to add quantity to."""
        all_move_lines = request.env['stock.move.line'].sudo()
        for m in scoped_moves:
            all_move_lines |= m.move_line_ids

        # Ưu tiên các dòng HÀNG LẺ trước (chưa đóng gói), sau đó mới đến packed
        all_move_lines = all_move_lines.sorted(
            key=lambda ml: (not bool(ml.result_package_id or ml.package_id), ml.id), reverse=True
        )

        barcode = scoped_moves[0].product_id.barcode if scoped_moves else '?'
        _logger.info(f"DEBUG_MOVE_LINES: Found {len(all_move_lines)} move_lines for barcode {barcode}. IDs: {all_move_lines.ids}")

        target_ml = None
        candidate_open_move = None

        for ml in all_move_lines:
            reserved_qty = getattr(ml, 'reserved_qty', 0) or getattr(ml, 'reserved_uom_qty', 0) or getattr(ml, 'product_uom_qty', 0) or 0
            remaining_in_line = reserved_qty - ml.qty_done

            _logger.info(f"CHECK MOVE_LINE {ml.id}: Move={ml.move_id.id}, Reserved={reserved_qty}, Done={ml.qty_done}, Remain={remaining_in_line}, PackageId={ml.package_id.id if ml.package_id else 'None'}, ResultPkg={ml.result_package_id.id if ml.result_package_id else 'None'}")

            if remaining_in_line > 0:
                target_ml = ml
                _logger.info(f"Selected move_line {ml.id} (Packed: {bool(ml.result_package_id)}) with remaining {remaining_in_line}")
                return target_ml

        # Kiểm tra move có dư demand không
        for m in scoped_moves:
            move_done = sum(ml.qty_done for ml in m.move_line_ids)
            move_remaining = m.product_uom_qty - move_done
            if move_remaining > 0:
                candidate_open_move = m
                _logger.info(f"Move {m.id} has remaining demand {move_remaining}. Will create new line.")
                break

        # Tạo line mới nếu cần
        if candidate_open_move:
            _logger.info(f"Creating new line for Move {candidate_open_move.id}")
            try:
                target_ml = request.env['stock.move.line'].sudo().create({
                    'picking_id': picking.id,
                    'move_id': candidate_open_move.id,
                    'product_id': candidate_open_move.product_id.id,
                    'product_uom_id': candidate_open_move.product_uom.id,
                    'location_id': candidate_open_move.location_id.id,
                    'location_dest_id': candidate_open_move.location_dest_id.id,
                    'qty_done': 0,
                })
                _logger.info(f"Created new line for Move {candidate_open_move.id}: {target_ml.id}")
                return target_ml
            except Exception as e:
                _logger.error(f"Failed to create move line: {e}")
                return None

        # Fallback: tìm loose line
        _logger.info("All move_lines are full or packed. Fallback to find any loose line.")
        loose_candidates = request.env['stock.move.line'].sudo().search([
            ('picking_id', '=', picking.id),
            ('product_id', 'in', scoped_moves.mapped('product_id').ids),
            ('move_id', 'in', scoped_moves.ids),
            ('result_package_id', '=', False)
        ], limit=1)

        if loose_candidates:
            target_ml = loose_candidates[0]
            _logger.info(f"Fallback: Found generic loose line: {target_ml.id}")
            return target_ml

        if scoped_moves:
            m = scoped_moves[0] if hasattr(scoped_moves, '__getitem__') else scoped_moves
            try:
                target_ml = request.env['stock.move.line'].sudo().create({
                    'picking_id': picking.id,
                    'move_id': m.id,
                    'product_id': m.product_id.id,
                    'product_uom_id': m.product_uom.id,
                    'location_id': m.location_id.id,
                    'location_dest_id': m.location_dest_id.id,
                    'qty_done': 0,
                })
                _logger.info(f"Fallback: Created new line for Move {m.id}: {target_ml.id}")
                return target_ml
            except:
                return None

        return None

    def _find_auto_target_subtract(self, scoped_moves):
        """Find a move_line to subtract quantity from (only unpacked lines)."""
        for move in scoped_moves:
            for ml in move.move_line_ids:
                if ml.qty_done > 0 and not ml.result_package_id:
                    return ml
        return None

    def _apply_qty_update(self, target_ml, delta):
        """Apply the qty_done delta to target_ml and return updated_lines list."""
        ml = target_ml
        current_qty = ml.qty_done
        move = ml.move_id
        updated_lines = []

        ml_reserved_qty = getattr(ml, 'reserved_qty', 0) or getattr(ml, 'reserved_uom_qty', 0) or getattr(ml, 'product_uom_qty', 0) or 0
        ml_remaining = max(0, ml_reserved_qty - current_qty)

        move_total_done = sum(l.qty_done for l in move.move_line_ids)
        move_remain = max(0, move.product_uom_qty - move_total_done)

        _logger.info(f"Updating line {ml.id}. Current: {current_qty}. ML Reserved: {ml_reserved_qty}. ML Remain: {ml_remaining}. Move Total: {move_total_done}. Move Remain: {move_remain}")

        if delta > 0:
            if ml_remaining > 0:
                add_qty = min(delta, ml_remaining)
            else:
                add_qty = min(delta, move_remain) if move_remain > 0 else delta

            if add_qty > 0:
                # Kiểm tra tồn kho tại vị trí
                if ml.location_id.usage == 'internal':
                    error = self._check_stock_availability(move, ml, add_qty)
                    if error:
                        return error  # Returns {"error": "..."} dict directly

                new_qty = current_qty + add_qty
                ml.write({'qty_done': new_qty})

                local_done_qty = sum(l.qty_done for l in move.move_line_ids)
                local_packed_qty = sum(l.qty_done for l in move.move_line_ids if l.result_package_id)

                _logger.info(f"Updated Done Qty: {new_qty}. Local Total: {local_done_qty}. Local Packed: {local_packed_qty}")

                updated_lines.append({
                    "line_id": ml.id,
                    "move_id": move.id,
                    "product": move.product_id.display_name,
                    "done_qty": local_done_qty,
                    "packed_qty": local_packed_qty,
                    "required_qty": move.product_uom_qty,
                    "barcode": move.product_id.barcode
                })

        elif delta < 0:
            reduce_qty = min(abs(delta), current_qty)
            if reduce_qty > 0:
                new_qty = current_qty - reduce_qty
                ml.write({'qty_done': new_qty})

                new_total_done_all = sum(l.qty_done for l in move.move_line_ids)

                updated_lines.append({
                    "line_id": ml.id,
                    "move_id": move.id,
                    "product": move.product_id.display_name,
                    "done_qty": new_total_done_all,
                    "required_qty": move.product_uom_qty,
                    "barcode": move.product_id.barcode
                })

        return updated_lines

    def _check_stock_availability(self, move, ml, add_qty):
        """Check if enough stock exists at the source location. Returns error dict or None."""
        try:
            quant = request.env['stock.quant'].sudo().search([
                ('product_id', '=', move.product_id.id),
                ('location_id', '=', ml.location_id.id)
            ], limit=1)

            available_in_loc = quant.quantity if quant else 0

            domain = [
                ('product_id', '=', move.product_id.id),
                ('location_id', '=', ml.location_id.id),
                ('state', 'not in', ['done', 'cancel'])
            ]
            all_lines_in_loc = request.env['stock.move.line'].search(domain)
            total_done_in_loc = sum(l.qty_done for l in all_lines_in_loc)

            if total_done_in_loc + add_qty > available_in_loc + 0.001:
                return {"error": f"⚠️ Vị trí {ml.location_id.display_name} không đủ tồn! (Hệ thống đang quét: {total_done_in_loc}, Muốn lấy thêm: {add_qty}. Kho chỉ có: {available_in_loc})"}
        except Exception as e:
            _logger.error(f"Lỗi khi kiểm tra tồn kho: {e}")
        return None

    # ===================== COMPLETE & PRINT =====================

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
                return {"error": f"⚠️ Sản phẩm '{move.product_id.display_name}' chưa đủ số lượng!"}
        try:
            picking.button_validate()
            return {"success": True, "message": f"✅ Phiếu {picking.name} đã được xác nhận!"}
        except Exception as e:
            return {"error": str(e)}

    @http.route('/pack_scan/check_and_print_label', type='json', auth='user', csrf=False)
    def check_and_print_label(self, **kwargs):
        picking_id = kwargs.get("picking_id")

        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            return {"error": "Phiếu không tồn tại"}

        package_ids = picking.move_line_ids.mapped('result_package_id').ids
        has_package = bool(package_ids)

        if has_package:
            return {
                "success": True,
                "has_package": True,
                "report_url": f"/report/pdf/hlv_pack_sequence.report_package_label_document/{picking_id}",
                "message": "✅ Đang in nhãn trước khi hoàn thành..."
            }
        else:
            return {
                "success": True,
                "has_package": False,
                "message": "Không có package, tiếp tục hoàn thành"
            }
