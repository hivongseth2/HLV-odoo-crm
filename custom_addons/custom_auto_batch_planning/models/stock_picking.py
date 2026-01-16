from odoo import models, api, fields
from datetime import date

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    planned_batch_id = fields.Many2one('stock.picking.batch', string='Dự kiến vào Lô', help='Lô dự kiến sẽ gán cho phiếu này khi hoàn tất')

    @api.model_create_multi
    def create(self, vals_list):
        # 1. Tạo phiếu
        pickings = super(StockPicking, self).create(vals_list)
        
        # 2. Logic mới: Truyền 'planned_batch_id' từ cha sang con
        for picking in pickings:
            self._propagate_planned_batch(picking)
        return pickings

    def write(self, vals):
        # 1. Write bình thường
        res = super(StockPicking, self).write(vals)
        
        # 2. Nếu có gán 'planned_batch_id' -> Lan truyền cho con
        if 'planned_batch_id' in vals:
            for picking in self:
                if picking.planned_batch_id:
                    self._propagate_planned_batch_downstream(picking, picking.planned_batch_id)
        return res

    def button_validate(self):
        res = super(StockPicking, self).button_validate()
        # Sau khi validate, check lại xem có cần truyền Plan cho con mới sinh ra ko
        for picking in self:
            self._propagate_planned_batch_downstream(picking, picking.planned_batch_id)
        return res

    def _propagate_planned_batch(self, picking):
        # 1. Tìm cha
        source_moves = picking.move_ids.mapped('move_orig_ids')
        if not source_moves:
            return

        prev_picking = source_moves[0].picking_id
        
        # 2. Nếu cha có Plan -> Con thừa kế Plan
        if prev_picking and prev_picking.planned_batch_id:
            picking.planned_batch_id = prev_picking.planned_batch_id
            
            # 3. ĐẶC BIỆT: Nếu con là phiếu OUT (Giao hàng) -> Gán vào Lô Thật luôn
            if picking.picking_type_code == 'outgoing':
                 self._assign_real_batch(picking, picking.planned_batch_id)

    def _propagate_planned_batch_downstream(self, picking, batch):
        if not batch:
            return
            
        next_moves = picking.move_ids.move_dest_ids
        next_pickings = next_moves.picking_id
        
        # Chỉ update những thằng chưa có plan hoặc plan khác
        pickings_to_update = next_pickings.filtered(lambda p: p.planned_batch_id != batch)
        
        if pickings_to_update:
            pickings_to_update.write({'planned_batch_id': batch.id})
            
            # Nếu trong đống con này có phiếu Out -> Gán lô thật
            for p in pickings_to_update:
                if p.picking_type_code == 'outgoing':
                    self._assign_real_batch(p, batch)

    def _assign_real_batch(self, picking, batch):
        # Logic gán lô thật (đảm bảo mở lô nếu done)
        if picking.batch_id == batch:
            return

        if batch.state == 'done':
            batch.write({'state': 'in_progress'})
            
        # Clear type constraint if needed
        if batch.picking_type_id and batch.picking_type_id != picking.picking_type_id:
             batch.picking_type_id = False
             
        try:
            picking.write({'batch_id': batch.id})
        except Exception:
            pass