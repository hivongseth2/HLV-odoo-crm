# -*- coding: utf-8 -*-

from odoo import models, fields, api, _

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def action_assign(self):
        """
        Ghi đè action_assign để phát hiện thiếu hàng và mở wizard cho người dùng chọn hủy dự trữ.
        """
        # 1. Thực hiện dự trữ tiêu chuẩn trước
        res = super(StockPicking, self).action_assign()
        
        # Nếu đang ở web client (thường là vậy khi nhấn nút), ta có thể trả về action
        if self.env.context.get('skip_unreserve_wizard'):
            return res

        for picking in self:
            if picking.state in ['done', 'cancel']:
                continue
                
            # Kiểm tra xem có dòng nào chưa được dự trữ đủ không
            moves_missing_stock = picking.move_ids_without_package.filtered(
                lambda m: m.state in ['confirmed', 'partially_available'] and m.product_uom_qty > sum(m.move_line_ids.mapped('quantity'))
            )
            
            if moves_missing_stock:
                # Tìm các nạn nhân tiềm năng
                victim_data = self._get_potential_unreserve_candidates(picking, moves_missing_stock)
                if victim_data:
                    # Mở wizard
                    wizard = self.env['stock.unreserve.wizard'].create({
                        'picking_id': picking.id,
                        'line_ids': [(0, 0, v) for v in victim_data]
                    })
                    return {
                        'name': _('Chọn đơn hàng để hủy dự trữ'),
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
        Thu thập thông tin các đơn hàng khác đang giữ hàng.
        """
        victim_data = []
        # Chặn trường hợp bị lặp nếu cùng 1 đơn hàng giữ nhiều move
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
            
            candidate_moves = self.env['stock.move'].search(domain)
            for cand in candidate_moves:
                if cand.id in processed_move_ids:
                    continue
                
                cand_reserved = sum(cand.move_line_ids.mapped('quantity'))
                if cand_reserved <= 0:
                    continue
                
                victim_data.append({
                    'picking_id': cand.picking_id.id,
                    'move_id': cand.id,
                    'product_id': product.id,
                    'reserved_qty': cand_reserved,
                    'uom_id': product.uom_id.id,
                    'deadline_date': getattr(cand.picking_id, 'x_studio_hn_giao_hng', False),
                })
                processed_move_ids.add(cand.id)
        
        return victim_data
