# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from datetime import date, datetime

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def action_assign(self):
        """
        Ghi đè action_assign để thực hiện ưu tiên dự trữ hàng.
        Nếu đơn hiện tại thiếu hàng, sẽ tự động hủy dự trữ các đơn có ngày giao xa nhất.
        """
        # 1. Thực hiện dự trữ tiêu chuẩn trước
        res = super(StockPicking, self).action_assign()
        
        # 2. Xử lý "cướp" hàng nếu vẫn chưa đủ
        for picking in self:
            if picking.state in ['done', 'cancel']:
                continue
                
            # Kiểm tra xem có dòng nào chưa được dự trữ đủ không
            # Odoo 17/18: dùng sum(m.move_line_ids.mapped('quantity')) để lấy số lượng đã dự trữ
            moves_missing_stock = picking.move_ids_without_package.filtered(
                lambda m: m.state in ['confirmed', 'partially_available'] and m.product_uom_qty > sum(m.move_line_ids.mapped('quantity'))
            )
            
            if moves_missing_stock:
                self._steal_stock_from_later_deadlines(picking, moves_missing_stock)
            
        return res

    def _steal_stock_from_later_deadlines(self, picking, moves_needing_stock):
        """
        Tìm các mặt hàng đang bị giữ bởi các đơn khác có hạn giao xa hơn và hủy dự trữ của chúng.
        """
        for move in moves_needing_stock:
            # Số lượng đã dự trữ hiện tại
            reserved_qty = sum(move.move_line_ids.mapped('quantity'))
            qty_needed = move.product_uom_qty - reserved_qty
            
            if qty_needed <= 0:
                continue

            product = move.product_id
            location_id = move.location_id
            
            # Tìm các move đang giữ hàng của cùng sản phẩm tại cùng vị trí
            domain = [
                ('product_id', '=', product.id),
                ('location_id', '=', location_id.id),
                ('state', 'in', ['assigned', 'partially_available']),
                ('picking_id', '!=', False),
                ('picking_id', '!=', picking.id),
                ('picking_id.state', 'in', ['assigned', 'partially_available']),
            ]
            
            candidate_moves = self.env['stock.move'].search(domain)
            if not candidate_moves:
                continue
                
            # Sắp xếp theo ngày giao hàng (x_studio_hn_giao_hng)
            # Ưu tiên các đơn KHÔNG có ngày giao (False) -> coi như xa vô tận
            def get_sort_key(m):
                deadline = getattr(m.picking_id, 'x_studio_hn_giao_hng', False)
                if not deadline:
                    return date.max
                return deadline

            # Sắp xếp giảm dần (Ngày xa nhất lên đầu)
            sorted_candidates = sorted(candidate_moves, key=get_sort_key, reverse=True)
            
            qty_freed = 0
            any_freed = False
            
            for cand in sorted_candidates:
                # Lấy số lượng mà move này đang giữ
                can_take = sum(cand.move_line_ids.mapped('quantity'))
                if can_take <= 0:
                    continue
                
                try:
                    # Ghi log tiếng Việt vào đơn bị hủy dự trữ
                    cand.picking_id.message_post(body=_(
                        "Hệ thống đã tự động hủy dự trữ %s %s của sản phẩm '%s' để ưu tiên cho đơn hàng %s."
                    ) % (can_take, product.uom_id.name, product.display_name, picking.name))
                    
                    # Hủy dự trữ
                    cand._do_unreserve()
                    
                    qty_freed += can_take
                    any_freed = True
                except Exception:
                    continue

                # Nếu đã đủ số lượng cần cướp thì dừng
                if qty_freed >= qty_needed:
                    break
            
            # Nếu có giải phóng được hàng, thử dự trữ lại cho đơn hiện tại
            if any_freed:
                try:
                    move._action_assign()
                except Exception:
                    pass
