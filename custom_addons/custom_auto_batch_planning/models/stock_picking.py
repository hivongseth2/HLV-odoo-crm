from odoo import models, fields, api

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def write(self, vals):
        # --- TÌNH HUỐNG 1: Khi user gán Batch cho phiếu PICK ---
        # Logic: Nếu field batch_id thay đổi, ta kích hoạt việc đồng bộ sang phiếu OUT
        res = super(StockPicking, self).write(vals)
        if 'batch_id' in vals:
            for picking in self:
                # Chỉ xử lý nếu đây là phiếu PICK (Lấy hàng nội bộ) và đã được gán Batch
                if picking.picking_type_code == 'internal' and picking.batch_id:
                    self._sync_batch_to_outgoing(picking)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        # --- TÌNH HUỐNG 2: Khi phiếu OUT mới được sinh ra ---
        # Logic: Vừa sinh ra là check ngay xem anh em (PICK) của nó có Batch chưa
        pickings = super(StockPicking, self).create(vals_list)
        for picking in pickings:
            if picking.picking_type_code == 'outgoing':
                # Tìm phiếu Pick anh em cùng nhóm mua sắm (cùng SO)
                sibling_pick = self.search([
                    ('group_id', '=', picking.group_id.id),
                    ('picking_type_code', '=', 'internal'),
                    ('batch_id', '!=', False) # Phải có Batch rồi mới tính
                ], limit=1)
                
                if sibling_pick:
                    # Gọi hàm đồng bộ từ Pick sang Out (đang là 'picking')
                    # Lưu ý: Truyền ngược tham số để tái sử dụng hàm
                    self._sync_batch_to_outgoing(sibling_pick, target_out_picking=picking)
        return pickings

    def _sync_batch_to_outgoing(self, pick_picking, target_out_picking=None):
        """
        Hàm core: Copy kế hoạch xe từ phiếu PICK sang phiếu OUT
        :param pick_picking: Phiếu Pick gốc (đã có Batch)
        :param target_out_picking: Phiếu Out đích (nếu chưa có thì tự đi tìm)
        """
        # 1. Nếu chưa biết phiếu Out nào, đi tìm phiếu Out cùng SO
        if not target_out_picking:
            target_out_picking = self.search([
                ('group_id', '=', pick_picking.group_id.id),
                ('picking_type_code', '=', 'outgoing'),
                ('state', 'not in', ['done', 'cancel'])
            ], limit=1)
        
        if not target_out_picking:
            return # Không tìm thấy phiếu Out nào thì dừng

        # 2. Lấy thông tin Xe và Tài xế từ Batch của phiếu Pick
        source_batch = pick_picking.batch_id
        vehicle = source_batch.vehicle_id
        driver = source_batch.user_id # Hoặc lấy driver từ vehicle

        if not vehicle:
            return # Batch Pick chưa gán xe thì thôi

        # 3. Tìm xem đã có Batch OUT nào cho chiếc xe này chưa (đang chạy/nháp)
        # Chúng ta cần tìm Batch loại "Giao hàng" (OUT) chứ không dùng chung Batch Pick
        Batch = self.env['stock.picking.batch']
        domain = [
            ('vehicle_id', '=', vehicle.id),
            ('state', 'in', ['draft', 'in_progress']),
            ('picking_type_id', '=', target_out_picking.picking_type_id.id) # Quan trọng: Batch loại OUT
        ]
        target_batch = Batch.search(domain, limit=1)

        # 4. Nếu chưa có Batch Out cho xe này -> Tạo mới
        if not target_batch:
            target_batch = Batch.create({
                'user_id': source_batch.user_id.id,
                'vehicle_id': vehicle.id,
                'dock_id': source_batch.dock_id.id,
                'company_id': target_out_picking.company_id.id,
                'picking_type_id': target_out_picking.picking_type_id.id, # Set type là Batch Giao hàng
                'note': f"Tự động tạo theo chuyến xe {vehicle.license_plate} từ khâu Lấy hàng"
            })

        # 5. Chốt đơn: Gán phiếu Out vào Batch vừa tìm được/tạo mới
        # Chỉ gán nếu nó chưa thuộc batch nào (để tránh ghi đè nếu user đã chỉnh tay)
        if not target_out_picking.batch_id:
            target_out_picking.write({'batch_id': target_batch.id})