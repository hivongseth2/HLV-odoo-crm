from odoo import models, fields, api

class StockBatchPlanning(models.Model):
    _name = 'stock.batch.planning'
    _description = 'Kế hoạch Gom Lô (Dự kiến)'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Mã kế hoạch', required=True, copy=False, readonly=True, default='New')
    scheduled_date = fields.Datetime(string='Ngày dự kiến', required=True, default=fields.Datetime.now, tracking=True)
    user_id = fields.Many2one('res.users', string='Tài xế/Phụ trách', tracking=True)
    vehicle_id = fields.Many2one('fleet.vehicle', string='Xe', tracking=True)
    route_name = fields.Char(string='Tuyến', tracking=True)
    
    picking_ids = fields.One2many('stock.picking', 'batch_plan_id', string='Các phiếu trong kế hoạch')
    
    # Link tới Batch thật khi đã convert
    batch_id = fields.Many2one('stock.picking.batch', string='Lô thực tế (Đã tạo)', readonly=True, copy=False)
    
    state = fields.Selection([
        ('draft', 'Nháp'),
        ('in_progress', 'Đang gom hàng'),
        ('ready', 'Sẵn sàng giao'),
        ('done', 'Đã tạo Lô'),
        ('cancel', 'Hủy')
    ], string='Trạng thái', default='draft', tracking=True)

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('stock.batch.planning') or 'New'
        return super(StockBatchPlanning, self).create(vals)

    def action_confirm(self):
        self.write({'state': 'in_progress'})

    def action_create_real_batch(self):
        """Chuyển đổi từ Kế hoạch -> Lô thật"""
        self.ensure_one()
        if self.batch_id:
            return
            
        # Tìm các phiếu OUT (Outgoing) trong kế hoạch này để đưa vào Lô thật
        # Hoặc đưa tất cả? Thường Lô giao hàng chỉ chứa phiếu Out hoặc phiếu đang cần xử lý.
        # User yêu cầu: "khi đạt điều kiện tất cả phiếu đã sinh phiếu OUT"
        # -> Ta sẽ tìm tất cả pickings thuộc plan này mà là Outgoing
        
        # Để an toàn, ta gom hết những phiếu đang có trong Plan mà chưa vào Batch nào
        pickings_to_batch = self.picking_ids.filtered(lambda p: not p.batch_id and p.state not in ['cancel', 'done'])
        
        # Ưu tiên phiếu OUT ? Hoặc gom hết (Pick -> Pack -> Out)
        # Thông thường Batch Giao hàng chỉ quan tâm phiếu Out.
        # Nhưng để tracking full flow, gom hết cũng được. 
        # Tuy nhiên Odoo standard Batch thường dùng cho operation cụ thể.
        # Theo yêu cầu: "tự nhảy vào batch đã tạo" -> Có thể là chỉ phiếu Out.
        
        if not pickings_to_batch:
            # Nếu ko có phiếu nào, vẫn tạo batch rỗng?
            pass

        Batch = self.env['stock.picking.batch']
        real_batch = Batch.create({
            'user_id': self.user_id.id,
            'vehicle_id': self.vehicle_id.id,
            'scheduled_date': self.scheduled_date,
            'picking_type_id': False, # Cho phép mix
            'route_name': self.route_name,
            'picking_ids': [(6, 0, pickings_to_batch.ids)]
        })
        
        self.write({
            'batch_id': real_batch.id,
            'state': 'done'
        })
