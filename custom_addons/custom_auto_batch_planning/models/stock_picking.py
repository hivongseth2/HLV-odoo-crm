from odoo import models, api, fields
from datetime import date

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    batch_plan_id = fields.Many2one('stock.batch.planning', string='Kế hoạch Gom Lô', help='Liên kết với kế hoạch gom lô')

    @api.model_create_multi
    def create(self, vals_list):
        # 1. Tạo phiếu
        pickings = super(StockPicking, self).create(vals_list)
        
        # 2. Logic mới: Truyền 'batch_plan_id' từ cha sang con
        for picking in pickings:
            self._propagate_batch_plan(picking)
        return pickings

    def write(self, vals):
        # 1. Write bình thường
        res = super(StockPicking, self).write(vals)
        
        # 2. Nếu có gán 'batch_plan_id' -> Lan truyền cho con
        if 'batch_plan_id' in vals:
            for picking in self:
                if picking.batch_plan_id:
                    self._propagate_batch_plan_downstream(picking, picking.batch_plan_id)
        return res

    def button_validate(self):
        res = super(StockPicking, self).button_validate()
        # Sau khi validate, check lại xem có cần truyền Plan cho con mới sinh ra ko
        for picking in self:
            self._propagate_batch_plan_downstream(picking, picking.batch_plan_id)
        return res

    def _propagate_batch_plan(self, picking):
        # 1. Tìm cha
        source_moves = picking.move_ids.mapped('move_orig_ids')
        if not source_moves:
            return

        prev_picking = source_moves[0].picking_id
        
        # 2. Nếu cha có Plan -> Con thừa kế Plan
        if prev_picking and prev_picking.batch_plan_id:
            picking.batch_plan_id = prev_picking.batch_plan_id
            
            # 3. ĐẶC BIỆT: Nếu con là phiếu OUT (Giao hàng) -> Tự động chui vào Lô Thật (nếu Plan đã có Lô Thật hoặc Auto-create)
            # Theo yêu cầu: "tự nhảy vào batch đã tạo"
            if picking.picking_type_code == 'outgoing':
                 self._check_and_assign_to_real_batch(picking, picking.batch_plan_id)

    def _propagate_batch_plan_downstream(self, picking, plan):
        if not plan:
            return
            
        next_moves = picking.move_ids.move_dest_ids
        next_pickings = next_moves.picking_id
        
        # Chỉ update những thằng chưa có plan hoặc plan khác
        pickings_to_update = next_pickings.filtered(lambda p: p.batch_plan_id != plan)
        
        if pickings_to_update:
            pickings_to_update.write({'batch_plan_id': plan.id})
            
            # Nếu trong đống con này có phiếu Out -> Check assign
            for p in pickings_to_update:
                if p.picking_type_code == 'outgoing':
                    self._check_and_assign_to_real_batch(p, plan)

    def _check_and_assign_to_real_batch(self, picking, plan):
        """
        Khi phiếu Out được gán vào Plan:
        1. Nếu Plan đã có 'batch_id' (Lô thật) -> Gán phiếu OUT vào Lô thật đó.
        2. Nếu Plan chưa có Lô thật -> Chưa làm gì (chờ user confirm trên Plan hoặc auto trigger khác)
           Nhưng user nói: "tự nhảy vào batch đã tạo".
        """
        if not plan or not plan.batch_id:
            return

        real_batch = plan.batch_id
        
        # Logic gán lô thật (đảm bảo mở lô nếu done)
        if picking.batch_id == real_batch:
            return

        if real_batch.state == 'done':
            real_batch.write({'state': 'in_progress'})
            
        # Clear type constraint if needed
        if real_batch.picking_type_id and real_batch.picking_type_id != picking.picking_type_id:
             real_batch.picking_type_id = False
             
        try:
    # Logic hiển thị tình trạng hàng chính xác theo yêu cầu (So Demand vs Reserved)
    availability_status_custom = fields.Selection([
        ('full', 'Đủ hàng'),
        ('partial', 'Thiếu hàng'),
        ('empty', 'Chưa có hàng')
    ], string='Tình trạng chi tiết', compute='_compute_availability_status_custom')

    @api.depends('move_ids.state', 'move_ids.product_uom_qty', 'move_ids.quantity_reserved')
    def _compute_availability_status_custom(self):
        for picking in self:
            if picking.state in ['done', 'cancel']:
                picking.availability_status_custom = 'full' if picking.state == 'done' else 'empty'
                continue
            
            # Chỉ check các move hoạt động (ko dính cancel)
            moves = picking.move_ids.filtered(lambda m: m.state not in ['cancel', 'done'])
            if not moves:
                picking.availability_status_custom = 'empty'
                continue

            # Check tỷ lệ
            # Nếu tất cả moves đều có reserved >= demand -> Full
            # Nếu có ít nhất 1 cái > 0 -> Partial
            # Còn lại empty
            
            is_full = True
            has_some = False
            
            for move in moves:
                # Dùng product_uom_qty (Demand) và quantity_reserved (Reserved)
                # Lưu ý xử lý case float rounding nếu cần, nhưng so sánh cơ bản ok
                if move.quantity_reserved < move.product_uom_qty:
                    is_full = False
                
                if move.quantity_reserved > 0:
                    has_some = True
            
            if is_full:
                picking.availability_status_custom = 'full'
            elif has_some:
                picking.availability_status_custom = 'partial'
            else:
                picking.availability_status_custom = 'empty'