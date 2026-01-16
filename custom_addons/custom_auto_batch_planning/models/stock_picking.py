from odoo import models, api, fields
from datetime import date

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    @api.model_create_multi
    def create(self, vals_list):
        # 1. Tạo phiếu trước
        pickings = super(StockPicking, self).create(vals_list)
        
        # 2. Xử lý logic gán batch ngay khi tạo (cho trường hợp Pack -> Out sinh ra sau)
        for picking in pickings:
             # Logic cũ: nếu move đã có sẵn (thường Odoo tạo move cùng lúc picking hoặc sau, nhưng check cho chắc)
             if picking.picking_type_code in ['internal', 'outgoing']:
                 self._auto_assign_batch(picking)
        return pickings

    def write(self, vals):
        # 1. Write bình thường
        res = super(StockPicking, self).write(vals)
        
        # 2. Nếu có thay đổi Batch -> Lan truyền xuống con cháu
        if 'batch_id' in vals:
            for picking in self:
                if picking.batch_id:
                    self._propagate_batch_to_downstream(picking, picking.batch_id)
        return res

    def button_validate(self):
        # 1. Chạy logic validate gốc (Odoo sẽ tạo/link các phiếu kế tiếp ở đây)
        res = super(StockPicking, self).button_validate()
        
        # 2. Sau khi validate, kiểm tra xem có phiếu con nào mới sinh ra không thì gán Lô luôn
        for picking in self:
            if picking.batch_id:
                self._propagate_batch_to_downstream(picking, picking.batch_id)
        return res

    def _auto_assign_batch(self, picking):
        # Logic này đôi khi chạy ở create nhưng picking chưa có move nếu tạo theo luồng chuẩn
        # Nên cứ giữ để catch các trường hợp có sẵn move.
        source_moves = picking.move_ids.mapped('move_orig_ids')
        if not source_moves:
            return

        prev_picking = source_moves[0].picking_id
        
        if prev_picking and prev_picking.batch_id:
            self._ensure_batch_allows_mixed_types(prev_picking.batch_id, picking.picking_type_id)
            picking.batch_id = prev_picking.batch_id

    def _propagate_batch_to_downstream(self, picking, batch):
        # Tìm phiếu con
        # Lưu ý: Khi validate xong, move_lines đã được update move_dest_ids
        next_moves = picking.move_ids.move_dest_ids
        next_pickings = next_moves.picking_id
        
        # Filter
        pickings_to_update = next_pickings.filtered(lambda p: p.batch_id != batch)
        
        if pickings_to_update:
            # Check type constraint
            if batch.picking_type_id:
                 conflicting = pickings_to_update.filtered(lambda p: p.picking_type_id != batch.picking_type_id)
                 if conflicting:
                     batch.picking_type_id = False
            
            # Gán batch
            pickings_to_update.write({'batch_id': batch.id})

    def _ensure_batch_allows_mixed_types(self, batch, picking_type):
        if batch.picking_type_id and batch.picking_type_id != picking_type:
            batch.picking_type_id = False