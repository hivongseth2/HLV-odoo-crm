from odoo import models, fields, api


class SaleOrderPlanning(models.Model):
    _inherit = 'sale.order'
    
    batch_plan_id = fields.Many2one('stock.batch.planning', string='Kế hoạch Gom Lô',
                                     help='Kế hoạch gom lô mà đơn hàng này thuộc về')

    def action_confirm(self):
        """Override để tự động link picking được sinh ra vào batch_plan_id"""
        res = super(SaleOrderPlanning, self).action_confirm()
        
        for order in self:
            if order.batch_plan_id:
                # Tìm picking vừa sinh ra từ SO này và gán batch_plan_id
                pickings = self.env['stock.picking'].search([
                    ('origin', '=', order.name),
                    ('batch_plan_id', '=', False),
                    ('state', 'not in', ['cancel', 'done'])
                ])
                if pickings:
                    pickings.write({'batch_plan_id': order.batch_plan_id.id})
        
        return res
