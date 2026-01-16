from odoo import models, fields

class StockPickingBatch(models.Model):
    _inherit = 'stock.picking.batch'
    
    route_name = fields.Char(string='Tuyến', help="Tên tuyến đường hoặc khu vực giao hàng")
