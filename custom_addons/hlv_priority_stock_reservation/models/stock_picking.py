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
                    # Tính summary tồn kho cho từng sản phẩm còn thiếu
                    summary_data = []
                    for move in moves_missing_stock:
                        already_reserved = sum(move.move_line_ids.mapped('quantity'))
                        still_needed = move.product_uom_qty - already_reserved
                        summary_data.append({
                            'product_id': move.product_id.id,
                            'location_id': move.location_id.id,
                            'demand_qty': move.product_uom_qty,
                            'already_reserved': already_reserved,
                            'still_needed': still_needed,
                            'uom_id': move.product_uom.id,
                        })
                    # Tạo và mở bảng chọn cho người dùng
                    wizard = self.env['stock.unreserve.wizard'].create({
                        'picking_id': picking.id,
                        'summary_ids': [(0, 0, s) for s in summary_data],
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
