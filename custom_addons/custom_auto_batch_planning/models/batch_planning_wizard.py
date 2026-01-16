from odoo import models, fields, api

class StockBatchPlanningWizard(models.TransientModel):
    _name = 'stock.batch.planning.wizard'
    _description = 'Wizard chọn Kế hoạch Gom Lô'

    batch_plan_id = fields.Many2one('stock.batch.planning', string='Chọn Kế hoạch', domain="[('state', 'in', ['draft', 'in_progress'])]")
    
    # Mode 2: Chọn Picking cho 1 Plan cụ thể
    mode = fields.Selection([('add_to_plan', 'Thêm vào Plan'), ('select_pickings', 'Chọn Picking cho Plan')], default='add_to_plan')
    picking_ids = fields.Many2many('stock.picking', string='Chọn Phiếu', domain="[('batch_plan_id', '=', False), ('state', 'in', ['confirmed', 'assigned'])]")

    @api.model
    def default_get(self, fields_list):
        res = super(StockBatchPlanningWizard, self).default_get(fields_list)
        if self.env.context.get('default_active_plan_id'):
            res['batch_plan_id'] = self.env.context.get('default_active_plan_id')
            res['mode'] = 'select_pickings'
        return res

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
