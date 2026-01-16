from odoo import models, fields, api

class StockBatchPlanningWizard(models.TransientModel):
    _name = 'stock.batch.planning.wizard'
    _description = 'Wizard chọn Kế hoạch Gom Lô'

    batch_plan_id = fields.Many2one('stock.batch.planning', string='Chọn Kế hoạch', domain="[('state', 'in', ['draft', 'in_progress'])]", required=True)
    
    def action_confirm(self):
        active_ids = self.env.context.get('active_ids', [])
        if active_ids:
            pickings = self.env['stock.picking'].browse(active_ids)
            pickings.write({'batch_plan_id': self.batch_plan_id.id})
            
            # Trigger logic propagation (đã có trong write của picking)
            if self.batch_plan_id.state in ['draft', 'in_progress']:
                # Nếu muốn chắc chắn, có thể gọi explicit propagation
                pass
        return {'type': 'ir.actions.act_window_close'}
