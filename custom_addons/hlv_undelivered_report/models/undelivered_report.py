from odoo import tools
from odoo import models, fields, api

class HlvUndeliveredReport(models.Model):
    _name = 'hlv.undelivered.report'
    _description = 'Undelivered Orders Report'
    _auto = False
    _rec_name = 'product_id'
    _order = 'move_date desc'

    move_id = fields.Many2one('stock.move', 'Move', readonly=True)
    picking_id = fields.Many2one('stock.picking', 'Picking', readonly=True)
    sale_line_id = fields.Many2one('sale.order.line', 'Sale Line', readonly=True)
    order_id = fields.Many2one('sale.order', 'Order', readonly=True)
    partner_id = fields.Many2one('res.partner', 'Customer', readonly=True)
    product_id = fields.Many2one('product.product', 'Product', readonly=True)
    product_uom = fields.Many2one('uom.uom', 'Unit of Measure', readonly=True)
    
    product_uom_qty = fields.Float('Demand', readonly=True)
    qty_reserved = fields.Float('Reserved', readonly=True)
    qty_delivered_line = fields.Float('Delivered (Line)', readonly=True, help="Total delivered quantity for the sale order line")
    
    state = fields.Selection([
        ('draft', 'New'),
        ('waiting', 'Waiting Another Move'),
        ('confirmed', 'Waiting'),
        ('assigned', 'Ready'),
        ('done', 'Done'),
        ('cancel', 'Cancelled'),
    ], string='Status', readonly=True)
    
    warehouse_id = fields.Many2one('stock.warehouse', 'Warehouse', readonly=True)
    move_date = fields.Datetime('Date', readonly=True)
    
    # Computed fields
    qty_on_hand = fields.Float('On Hand (Warehouse)', compute='_compute_qty_on_hand')

    @api.depends('product_id', 'warehouse_id')
    def _compute_qty_on_hand(self):
        for record in self:
            if record.product_id and record.warehouse_id:
                record.qty_on_hand = record.product_id.with_context(warehouse=record.warehouse_id.id).qty_available
            else:
                record.qty_on_hand = record.product_id.qty_available

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW hlv_undelivered_report AS (
                SELECT
                    sm.id as id,
                    sm.id as move_id,
                    sm.picking_id,
                    sm.sale_line_id,
                    so.id as order_id,
                    so.partner_id,
                    sm.product_id,
                    sm.product_uom,
                    sm.product_uom_qty,
                    sm.reserved_availability as qty_reserved,
                    sol.qty_delivered as qty_delivered_line,
                    sm.state as state,
                    sm.warehouse_id,
                    sm.date as move_date
                FROM
                    stock_move sm
                    JOIN sale_order_line sol ON sm.sale_line_id = sol.id
                    JOIN sale_order so ON sol.order_id = so.id
                WHERE
                    sm.state NOT IN ('done', 'cancel')
                    AND so.state IN ('sale', 'done')
            )
        """)
