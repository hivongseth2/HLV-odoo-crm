from odoo import tools
from odoo import models, fields, api

class HlvUndeliveredReport(models.Model):
    _name = 'hlv.undelivered.report'
    _description = 'Undelivered Orders Report'
    _auto = False
    _rec_name = 'product_id'
    _order = 'move_date desc'

    move_id = fields.Many2one('stock.move', 'Dịch chuyển', readonly=True)
    picking_id = fields.Many2one('stock.picking', 'Phiếu kho', readonly=True)
    sale_line_id = fields.Many2one('sale.order.line', 'Dòng đơn hàng', readonly=True)
    order_id = fields.Many2one('sale.order', 'Đơn hàng', readonly=True)
    partner_id = fields.Many2one('res.partner', 'Khách hàng', readonly=True)
    product_id = fields.Many2one('product.product', 'Sản phẩm', readonly=True)
    product_uom = fields.Many2one('uom.uom', 'Đơn vị tính', readonly=True)
    
    product_uom_qty = fields.Float('Nhu cầu hiện tại', readonly=True)
    original_demand = fields.Float('Nhu cầu gốc (SO)', readonly=True)
    qty_reserved = fields.Float('Đã giữ', readonly=True)
    qty_delivered_line = fields.Float('Đã giao (Dòng)', readonly=True, help="Tổng số lượng đã giao cho dòng đơn hàng này")
    
    state = fields.Selection([
        ('draft', 'Mới'),
        ('waiting', 'Chờ dịch chuyển khác'),
        ('confirmed', 'Đang chờ'),
        ('assigned', 'Sẵn sàng'),
        ('done', 'Hoàn thành'),
        ('cancel', 'Đã hủy'),
    ], string='Trạng thái', readonly=True)
    
    warehouse_id = fields.Many2one('stock.warehouse', 'Kho', readonly=True)
    move_date = fields.Datetime('Ngày', readonly=True)
    
    # Computed fields
    qty_on_hand = fields.Float('Tồn kho (Tại kho)', compute='_compute_qty_on_hand')

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
                    sol.product_uom_qty as original_demand,
                    COALESCE((SELECT SUM(sml.quantity) FROM stock_move_line sml WHERE sml.move_id = sm.id), 0.0) as qty_reserved,
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

