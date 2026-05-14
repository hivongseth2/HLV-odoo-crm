# -*- coding: utf-8 -*-

from odoo import models, fields, api, _

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def action_assign(self):
        """
        Ghi đè action_assign:
        1. Dự trữ hàng trống trước.
        2. Nếu vẫn thiếu, hiện bảng chọn để rút hàng từ đơn khác.
        """
        # 1. Thực hiện dự trữ hàng có sẵn trong kho trước (Standard Odoo)
        res = super(StockPicking, self).action_assign()

        # Sau khi super() chạy, Odoo có thể tăng move_line.quantity mà không update
        # quant.reserved_quantity nếu dữ liệu quant không nhất quán (inconsistent).
        # Sync lại quant.reserved để tránh "reservation bay" tích lũy mỗi lần gọi.
        self._sync_quant_reserved_from_move_lines()

        # Nếu được gọi từ wizard hoặc context bỏ qua thì không mở lại wizard
        if self.env.context.get('skip_unreserve_wizard'):
            return res

        for picking in self:
            if picking.state in ['done', 'cancel']:
                continue
                
            # Kiểm tra xem sau khi dự trữ hàng trống, có dòng nào vẫn còn thiếu không
            moves_missing_stock = picking.move_ids_without_package.filtered(
                lambda m: m.state in ['confirmed', 'partially_available'] and m.product_uom_qty > sum(m.move_line_ids.mapped('quantity'))
            )
            
            if moves_missing_stock:
                # Tìm các đơn hàng khác đang giữ sản phẩm này
                victim_data = self._get_potential_unreserve_candidates(picking, moves_missing_stock)
                if victim_data:
                    # Tạo và mở bảng chọn cho người dùng
                    wizard = self.env['stock.unreserve.wizard'].create({
                        'picking_id': picking.id,
                        'line_ids': [(0, 0, v) for v in victim_data]
                    })
                    return {
                        'name': _('Rút hàng dự trữ từ các đơn khác'),
                        'type': 'ir.actions.act_window',
                        'res_model': 'stock.unreserve.wizard',
                        'view_mode': 'form',
                        'res_id': wizard.id,
                        'target': 'new',
                        'context': self.env.context,
                    }
            
        return res


    def _get_potential_unreserve_candidates(self, picking, moves_needing_stock):
        """
        Lấy danh sách các move đang dự trữ hàng mà đơn hiện tại đang cần.
        """
        victim_data = []
        processed_move_ids = set()

        for move in moves_needing_stock:
            product = move.product_id
            location_id = move.location_id
            
            domain = [
                ('product_id', '=', product.id),
                ('location_id', '=', location_id.id),
                ('state', 'in', ['assigned', 'partially_available']),
                ('picking_id', '!=', False),
                ('picking_id', '!=', picking.id),
                ('picking_id.state', 'in', ['assigned', 'partially_available']),
            ]
            
            # Sắp xếp các ứng viên tiềm năng: Ưu tiên đơn có ngày giao xa nhất lên trước cho người dùng dễ chọn
            candidate_moves = self.env['stock.move'].search(domain)
            
            # Sắp xếp trong Python vì x_studio_hn_giao_hng là studio field
            def sort_deadline(m):
                d = getattr(m.picking_id, 'x_studio_hn_giao_hng', False)
                if d:
                    d = fields.Date.to_date(d)
                return d or picking.env.context.get('max_date', fields.Date.today().replace(year=2099))

            sorted_candidates = sorted(candidate_moves, key=sort_deadline, reverse=True)

            for cand in sorted_candidates:
                if cand.id in processed_move_ids:
                    continue
                
                cand_reserved = sum(cand.move_line_ids.mapped('quantity'))
                if cand_reserved <= 0:
                    continue
                
                victim_data.append({
                    'picking_id': cand.picking_id.id,
                    'origin': cand.picking_id.origin,
                    'move_id': cand.id,
                    'product_id': product.id,
                    'reserved_qty': cand_reserved,
                    'demand_qty': cand.product_uom_qty,
                    'uom_id': product.uom_id.id,
                    'deadline_date': getattr(cand.picking_id, 'x_studio_hn_giao_hng', False),
                })
                processed_move_ids.add(cand.id)
        
        return victim_data

    def _sync_quant_reserved_from_move_lines(self):
        """
        Sau khi action_assign, Odoo có thể tăng move_line.quantity nhưng KHÔNG update
        quant.reserved_quantity nếu quant đang ở trạng thái inconsistent (reserved < actual ML).
        Method này sync lại quant.reserved = sum(move_lines) tại mỗi location,
        đảm bảo không có "reservation bay" tích lũy mỗi lần gọi action_assign.
        """
        Quant = self.env['stock.quant']
        affected_product_locs = set()

        for picking in self:
            for ml in picking.move_line_ids:
                if ml.state in ('cancel', 'done'):
                    continue
                affected_product_locs.add((ml.product_id.id, ml.location_id.id))

        for product_id, location_id in affected_product_locs:
            # Tổng tất cả move_lines đang claim tại location này
            mls = self.env['stock.move.line'].search([
                ('product_id', '=', product_id),
                ('location_id', '=', location_id),
                ('state', 'not in', ('cancel', 'done')),
            ])
            total_ml_qty = sum(ml.quantity for ml in mls)

            quants = Quant.search([
                ('product_id', '=', product_id),
                ('location_id', '=', location_id),
            ])
            if not quants:
                continue

            total_quant_qty = sum(q.quantity for q in quants)
            # reserved không được vượt quá qty thực tế và không được ít hơn 0
            correct_reserved = max(0.0, min(total_ml_qty, total_quant_qty))

            for q in quants:
                if abs(q.reserved_quantity - correct_reserved) > 0.001:
                    _logger.info(
                        'Sync quant %d (%s): reserved %s → %s (ml_total=%s, qty=%s)',
                        q.id, q.location_id.complete_name,
                        q.reserved_quantity, correct_reserved,
                        total_ml_qty, total_quant_qty,
                    )
                    self.env.cr.execute(
                        'UPDATE stock_quant SET reserved_quantity = %s WHERE id = %s',
                        (correct_reserved, q.id),
                    )
                    q.invalidate_recordset(['reserved_quantity'])
