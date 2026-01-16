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
        
        # 2. Nếu phiếu cha có Lô và có Xe -> Thì mới làm tiếp
        if prev_picking and prev_picking.batch_id and prev_picking.batch_id.vehicle_id:
            vehicle = prev_picking.batch_id.vehicle_id
            driver = prev_picking.batch_id.user_id
            
            # --- LOGIC THÔNG MINH (V3) ---
            # Tìm Lô đang mở, CÙNG XE, CÙNG LOẠI PHIẾU, và phải CÙNG NGÀY DỰ KIẾN
            # Để tránh gom nhầm vào lô cũ của ngày hôm qua
            
            today = fields.Date.context_today(self)
            
            Batch = self.env['stock.picking.batch']
            domain = [
                ('vehicle_id', '=', vehicle.id),
                ('state', 'in', ['draft', 'in_progress']),
                ('picking_type_id', '=', picking.picking_type_id.id),
            ]
            
            # Tìm các lô khớp xe
            candidate_batches = Batch.search(domain)
            target_batch = False

            # Lọc lại bằng Python để chắc chắn đúng ngày (vì scheduled_date có thể có giờ phút)
            for batch in candidate_batches:
                if batch.scheduled_date and batch.scheduled_date.date() == today:
                    target_batch = batch
                    break
            
            # 3. Nếu không tìm thấy Lô nào của HÔM NAY -> Tạo mới
            if not target_batch:
                target_batch = Batch.create({
                    'user_id': driver.id,
                    'vehicle_id': vehicle.id,
                    'dock_id': prev_picking.batch_id.dock_id.id,
                    'company_id': picking.company_id.id,
                    'picking_type_id': picking.picking_type_id.id,
                    'scheduled_date': fields.Datetime.now(), # Gán ngày hôm nay
                    'note': f"Tự động tạo từ chuyến xe {vehicle.license_plate} - Ngày {today}"
                })

            # 4. Gán phiếu vào Lô
            picking.write({'batch_id': target_batch.id})