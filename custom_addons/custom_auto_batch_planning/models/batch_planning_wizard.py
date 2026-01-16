from odoo import models, fields, api
from datetime import timedelta

class StockBatchPlanningWizard(models.TransientModel):
    _name = 'stock.batch.planning.wizard'
    _description = 'Wizard chọn Kế hoạch Gom Lô'

    batch_plan_id = fields.Many2one('stock.batch.planning', string='Chọn Kế hoạch', domain="[('state', 'in', ['draft', 'in_progress'])]")
    
    # Mode 2: Chọn Picking cho 1 Plan cụ thể
    mode = fields.Selection([('add_to_plan', 'Thêm vào Plan'), ('select_pickings', 'Chọn Picking cho Plan')], default='add_to_plan')
    # Danh sách chính (theo bộ lọc ngày)
    picking_ids = fields.Many2many('stock.picking', 'wizard_picking_rel', 'wizard_id', 'picking_id', string='Chọn Phiếu (Theo Ngày)', 
                                   domain="[('batch_plan_id', '=', False), ('state', 'in', ['confirmed', 'assigned']), ('picking_type_id.sequence_code', '=', 'PICK')]")
                                   
    # Danh sách gợi ý (theo Partner của các phiếu đã chọn ở trên)
    additional_picking_ids = fields.Many2many('stock.picking', 'wizard_additional_picking_rel', 'wizard_id', 'picking_id', string='Gợi ý cùng Khách hàng (Phiếu cũ/Tồn đọng)')

    # Smart Filter Fields
    search_date = fields.Date(string='Ngày dự kiến')
    search_partner_id = fields.Many2one('res.partner', string='Lọc Khách hàng')

    @api.model
    def default_get(self, fields_list):
        res = super(StockBatchPlanningWizard, self).default_get(fields_list)
        if self.env.context.get('default_active_plan_id'):
            plan = self.env['stock.batch.planning'].browse(self.env.context.get('default_active_plan_id'))
            res['batch_plan_id'] = plan.id
            res['mode'] = 'select_pickings'
            # Default search date theo Plan
            res['search_date'] = plan.scheduled_date.date() if plan.scheduled_date else fields.Date.today()
        return res

    @api.onchange('search_date', 'search_partner_id')
    def _onchange_search_criteria(self):
        domain = [('batch_plan_id', '=', False), 
                  ('state', 'in', ['confirmed', 'assigned']), 
                  ('picking_type_id.sequence_code', '=', 'PICK')]
        
        # Filter CHÍNH chỉ tác động vào picking_ids (List trên)
        if self.search_date:
            domain += [('scheduled_date', '>=', self.search_date), 
                       ('scheduled_date', '<', self.search_date + timedelta(days=1))]
        
        if self.search_partner_id:
            domain += ['|', ('partner_id', 'child_of', self.search_partner_id.id), 
                            ('partner_id', '=', self.search_partner_id.id)]
                            
        return {'domain': {'picking_ids': domain}}

    @api.onchange('picking_ids')
    def _onchange_picking_ids(self):
        """
        Khi người dùng chọn phiếu ở List Chính:
        -> Tìm các phiếu khác CÙNG PARTNER (nhưng không nằm trong list chính) để gợi ý vào List Phụ.
        """
        if not self.picking_ids:
            self.additional_picking_ids = [(5, 0, 0)] # Clear list
            return

        selected_partners = self.picking_ids.mapped('partner_id')
        if not selected_partners:
            return

        # Tìm các phiếu:
        # 1. Thuộc partner đã chọn (hoặc con cái)
        # 2. Chưa có Plan
        # 3. Là PICK
        # 4. KHÔNG nằm trong danh sách picking_ids đang hiển thị (để tránh trùng)
        
        # Xây dựng domain partner
        partner_ids = selected_partners.ids
        # Mở rộng search con cái nếu cần, nhưng cẩn thận perf. Ở đây search thẳng ID trước.
        
        domain_suggestion = [
            ('batch_plan_id', '=', False),
            ('state', 'in', ['confirmed', 'assigned']),
            ('picking_type_id.sequence_code', '=', 'PICK'),
            ('id', 'not in', self.picking_ids.ids),
            ('partner_id', 'in', partner_ids)
        ]
        
        suggested = self.env['stock.picking'].search(domain_suggestion)
        self.additional_picking_ids = [(6, 0, suggested.ids)]

    def action_confirm(self):
        if self.mode == 'add_to_plan':
            # Case 1: Từ list Picking -> Chọn Plan
            active_ids = self.env.context.get('active_ids', [])
            if active_ids and self.batch_plan_id:
                pickings = self.env['stock.picking'].browse(active_ids)
                pickings.write({'batch_plan_id': self.batch_plan_id.id})
                
        elif self.mode == 'select_pickings':
             # Case 2: Từ Plan -> Chọn Picking
             # GỘP CẢ 2 DANH SÁCH
             all_pickings = self.picking_ids | self.additional_picking_ids
             
             if self.batch_plan_id and all_pickings:
                 all_pickings.write({'batch_plan_id': self.batch_plan_id.id})
                 
        return {'type': 'ir.actions.act_window_close'}
