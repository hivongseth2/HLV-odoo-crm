from odoo import models, api, fields
from datetime import date

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    @api.model_create_multi
    def create(self, vals_list):
        pickings = super(StockPicking, self).create(vals_list)
        for picking in pickings:
            # Chỉ chạy logic này cho phiếu Pack (đóng gói) hoặc Out (giao hàng)
            # Tránh chạy cho phiếu Pick hoặc các loại khác không cần thiết
            if picking.picking_type_code in ['internal', 'outgoing']: 
                self._auto_assign_batch(picking)
        return pickings

    def _auto_assign_batch(self, picking):
        # 1. Truy vết ngược: Tìm xem phiếu cha (Pick) là ai?
        source_moves = picking.move_ids.mapped('move_orig_ids')
        if not source_moves:
            return

        prev_picking = source_moves[0].picking_id
        
        # 2. Logic mới: Nếu phiếu pick đã vào lô, phiếu out sinh ra cũng vào chung lô đó
        if prev_picking and prev_picking.batch_id:
            picking.batch_id = prev_picking.batch_id