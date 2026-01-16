from odoo import models, fields

class StockPickingBatch(models.Model):
    _inherit = 'stock.picking.batch'
    
    route_name = fields.Char(string='Tuyến', help="Tên tuyến đường hoặc khu vực giao hàng")
    vehicle_id = fields.Many2one('fleet.vehicle', string='Xe', help='Xe vận chuyển lô hàng này')
    dock_id = fields.Many2one('stock.location', string='Dock', domain="[('usage', '=', 'view')]")
    planned_picking_ids = fields.One2many('stock.picking', 'planned_batch_id', string='Phiếu dự kiến')
