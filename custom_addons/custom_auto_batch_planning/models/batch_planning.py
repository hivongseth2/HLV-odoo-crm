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
    
    # NEW: Liên kết trực tiếp với Sale Order
    sale_order_ids = fields.Many2many('sale.order', 'batch_planning_sale_order_rel', 
                                       'plan_id', 'order_id', string='Đơn hàng trong kế hoạch')
    
    # NEW: Bộ lọc theo Tag (Tuyến) - Many2many vì SO có nhiều tag
    tag_ids = fields.Many2many('crm.tag', 'batch_planning_tag_rel',
                               'plan_id', 'tag_id', string='Lọc theo Tuyến (Tag)')
    filter_parent_partner_id = fields.Many2one('res.partner', string='Lọc theo Công ty mẹ',
                                                domain="[('is_company', '=', True)]")
    commitment_date_from = fields.Date(string='Ngày giao từ')
    commitment_date_to = fields.Date(string='Ngày giao đến')
    
    # NEW: Computed counts
    sale_order_count = fields.Integer(compute='_compute_counts', string='Số đơn hàng')
    picking_count = fields.Integer(compute='_compute_counts', string='Số phiếu')
    
    # Link tới Batch thật khi
    batch_id = fields.Many2one('stock.picking.batch', string='Lô thực tế (Đã tạo)', readonly=True, copy=False)
    
    state = fields.Selection([
        ('draft', 'Nháp'),
        ('in_progress', 'Đang gom hàng'),
        ('ready', 'Sẵn sàng giao'),
        ('done', 'Đã tạo Lô'),
        ('cancel', 'Hủy')
    ], string='Trạng thái', default='draft', tracking=True)

    @api.depends('sale_order_ids', 'picking_ids')
    def _compute_counts(self):
        for record in self:
            record.sale_order_count = len(record.sale_order_ids)
            record.picking_count = len(record.picking_ids)

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
        
    def action_open_picking_selector(self):
        self.ensure_one()
        return {
            'name': 'Chọn Phiếu Xuất Kho',
            'type': 'ir.actions.act_window',
            'res_model': 'stock.batch.planning.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_active_plan_id': self.id,
                'default_mode': 'select_pickings'
            }
        }

    def action_add_sale_orders(self):
        """Mở wizard để chọn Sale Order vào kế hoạch"""
        self.ensure_one()
        return {
            'name': 'Chọn Đơn Hàng (SO)',
            'type': 'ir.actions.act_window',
            'res_model': 'stock.batch.planning.so.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_batch_plan_id': self.id,
                'default_tag_ids': [(6, 0, self.tag_ids.ids)] if self.tag_ids else False,
                'default_parent_partner_id': self.filter_parent_partner_id.id if self.filter_parent_partner_id else False,
                'default_commitment_date_from': self.commitment_date_from,
                'default_commitment_date_to': self.commitment_date_to,
            }
        }

    def _sync_pickings_from_sale_orders(self):
        """Đồng bộ Picking từ các Sale Order trong kế hoạch"""
        for plan in self:
            for so in plan.sale_order_ids:
                # Tìm các picking liên quan từ SO
                pickings = self.env['stock.picking'].search([
                    ('origin', '=', so.name),
                    ('batch_plan_id', '=', False),
                    ('state', 'not in', ['cancel', 'done'])
                ])
                if pickings:
                    pickings.write({'batch_plan_id': plan.id})
