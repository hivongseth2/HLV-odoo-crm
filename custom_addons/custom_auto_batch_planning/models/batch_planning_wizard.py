from odoo import models, fields, api
from datetime import timedelta

class StockBatchPlanningWizard(models.TransientModel):
    _name = 'stock.batch.planning.wizard'
    _description = 'Wizard chọn Kế hoạch Gom Lô'

    batch_plan_id = fields.Many2one('stock.batch.planning', string='Chọn Kế hoạch', domain="[('state', 'in', ['draft', 'in_progress'])]")
    
    # Mode 2: Chọn Picking cho 1 Plan cụ thể
    mode = fields.Selection([('add_to_plan', 'Thêm vào Plan'), ('select_pickings', 'Chọn Picking cho Plan')], default='add_to_plan')
    picking_ids = fields.Many2many('stock.picking', string='Chọn Phiếu', 
                                   domain="[('batch_plan_id', '=', False), ('state', 'in', ['confirmed', 'assigned']), ('picking_type_id.sequence_code', '=', 'PICK')]")

    # Smart Filter Fields
    search_date = fields.Date(string='Ngày dự kiến')
    search_partner_id = fields.Many2one('res.partner', string='Khách hàng (Công ty)')

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
        
        if self.search_partner_id:
            # Lọc theo partner (bao gồm cả công ty mẹ/con)
            # Logic: Nếu đã chọn Partner -> Bỏ qua lọc ngày để tìm tất cả các phiếu tồn đọng (Backlog)
            # Theo yêu cầu: "coi công ty đó còn có phiếu nào chưa giao không... chọn thêm"
            domain += ['|', ('partner_id', 'child_of', self.search_partner_id.id), 
                            ('partner_id', '=', self.search_partner_id.id)]
        
        elif self.search_date:
            # Nếu chưa chọn Partner -> Lọc theo Ngày
            # Fix logic ngày: so sánh start of day <= date < start of next day
            domain += [('scheduled_date', '>=', self.search_date), 
                       ('scheduled_date', '<', self.search_date + timedelta(days=1))]
                            
        return {'domain': {'picking_ids': domain}}

    def action_confirm(self):
        if self.mode == 'add_to_plan':
            # Case 1: Từ list Picking -> Chọn Plan
            active_ids = self.env.context.get('active_ids', [])
            if active_ids and self.batch_plan_id:
                pickings = self.env['stock.picking'].browse(active_ids)
                pickings.write({'batch_plan_id': self.batch_plan_id.id})
                
        elif self.mode == 'select_pickings':
             # Case 2: Từ Plan -> Chọn Picking
             if self.batch_plan_id and self.picking_ids:
                 self.picking_ids.write({'batch_plan_id': self.batch_plan_id.id})
                 
        return {'type': 'ir.actions.act_window_close'}
