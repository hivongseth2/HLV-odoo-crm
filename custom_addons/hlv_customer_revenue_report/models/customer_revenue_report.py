from odoo import tools
from odoo import fields, models


class HlvCustomerRevenueReport(models.Model):
    _name = 'hlv.customer.revenue.report'
    _description = 'Báo cáo doanh thu theo khách hàng'
    _auto = False
    _rec_name = 'sale_order_id'
    _order = 'date_done desc'

    # ==================== Relations ====================
    move_id = fields.Many2one('stock.move', string='Dịch chuyển kho', readonly=True)
    picking_id = fields.Many2one('stock.picking', string='Phiếu xuất kho', readonly=True)
    picking_type_id = fields.Many2one('stock.picking.type', string='Loại thao tác', readonly=True)
    sale_line_id = fields.Many2one('sale.order.line', string='Dòng đơn hàng', readonly=True)
    sale_order_id = fields.Many2one('sale.order', string='Đơn hàng', readonly=True)
    company_id = fields.Many2one('res.company', string='Công ty', readonly=True)
    warehouse_id = fields.Many2one('stock.warehouse', string='Kho', readonly=True)
    user_id = fields.Many2one('res.users', string='Nhân viên bán hàng', readonly=True)
    order_partner_id = fields.Many2one('res.partner', string='Người đặt hàng', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Khách hàng', readonly=True)
    product_id = fields.Many2one('product.product', string='Sản phẩm', readonly=True)
    product_categ_id = fields.Many2one('product.category', string='Nhóm sản phẩm', readonly=True)
    product_uom_id = fields.Many2one('uom.uom', string='Đơn vị tính', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Tiền tệ', readonly=True)

    # ==================== Dates ====================
    order_date = fields.Datetime(string='Ngày đặt hàng', readonly=True)
    date_done = fields.Datetime(string='Ngày xuất kho', readonly=True)

    # ==================== Quantities ====================
    qty_delivered = fields.Float(string='SL xuất kho', readonly=True)
    qty_returned = fields.Float(string='SL trả hàng', readonly=True)
    qty_net = fields.Float(string='SL thực xuất (ròng)', readonly=True)

    # ==================== Unit prices ====================
    price_unit_after_tax = fields.Float(string='Đơn giá (sau thuế)', readonly=True)
    price_unit_before_tax = fields.Float(string='Đơn giá (trước thuế)', readonly=True)

    # ==================== Amounts ====================
    amount_gross = fields.Monetary(
        string='Doanh thu xuất kho (gộp, sau thuế)', currency_field='currency_id', readonly=True,
        help='Tiền hàng đã xuất kho theo đơn giá sau thuế của dòng đơn bán (chưa trừ trả hàng).',
    )
    amount_returned = fields.Monetary(
        string='Tiền hàng trả lại (sau thuế)', currency_field='currency_id', readonly=True,
        help='Giá trị (theo đơn giá sau thuế) phần hàng đã bị khách trả lại, xác định qua '
             'stock.move.origin_returned_move_id của các phiếu nhập trả hàng.',
    )
    amount_net = fields.Monetary(
        string='Doanh thu xuất ròng (sau thuế)', currency_field='currency_id', readonly=True,
        help='= Doanh thu xuất kho (gộp) - Tiền hàng trả lại.',
    )
    amount_gross_untaxed = fields.Monetary(
        string='Doanh thu xuất kho (gộp, trước thuế)', currency_field='currency_id', readonly=True,
    )
    amount_net_untaxed = fields.Monetary(
        string='Doanh thu xuất ròng (trước thuế)', currency_field='currency_id', readonly=True,
    )

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW hlv_customer_revenue_report AS (
                WITH move_return AS (
                    SELECT
                        origin_returned_move_id AS move_id,
                        SUM(quantity) AS returned_qty
                    FROM stock_move
                    WHERE state = 'done' AND origin_returned_move_id IS NOT NULL
                    GROUP BY origin_returned_move_id
                )
                SELECT
                    sm.id AS id,
                    sm.id AS move_id,
                    sm.picking_id AS picking_id,
                    sp.picking_type_id AS picking_type_id,
                    sm.sale_line_id AS sale_line_id,
                    sol.order_id AS sale_order_id,
                    so.company_id AS company_id,
                    spt.warehouse_id AS warehouse_id,
                    so.user_id AS user_id,
                    so.partner_id AS order_partner_id,
                    COALESCE(rp.commercial_partner_id, so.partner_id) AS partner_id,
                    sm.product_id AS product_id,
                    pt.categ_id AS product_categ_id,
                    sm.product_uom AS product_uom_id,
                    sol.currency_id AS currency_id,

                    so.date_order AS order_date,
                    sp.date_done AS date_done,

                    sm.quantity AS qty_delivered,
                    COALESCE(mr.returned_qty, 0.0) AS qty_returned,
                    (sm.quantity - COALESCE(mr.returned_qty, 0.0)) AS qty_net,

                    CASE WHEN sol.product_uom_qty != 0
                         THEN sol.price_total / sol.product_uom_qty ELSE 0.0 END AS price_unit_after_tax,
                    CASE WHEN sol.product_uom_qty != 0
                         THEN sol.price_subtotal / sol.product_uom_qty ELSE 0.0 END AS price_unit_before_tax,

                    sm.quantity * (CASE WHEN sol.product_uom_qty != 0
                        THEN sol.price_total / sol.product_uom_qty ELSE 0.0 END) AS amount_gross,
                    COALESCE(mr.returned_qty, 0.0) * (CASE WHEN sol.product_uom_qty != 0
                        THEN sol.price_total / sol.product_uom_qty ELSE 0.0 END) AS amount_returned,
                    (sm.quantity - COALESCE(mr.returned_qty, 0.0)) * (CASE WHEN sol.product_uom_qty != 0
                        THEN sol.price_total / sol.product_uom_qty ELSE 0.0 END) AS amount_net,

                    sm.quantity * (CASE WHEN sol.product_uom_qty != 0
                        THEN sol.price_subtotal / sol.product_uom_qty ELSE 0.0 END) AS amount_gross_untaxed,
                    (sm.quantity - COALESCE(mr.returned_qty, 0.0)) * (CASE WHEN sol.product_uom_qty != 0
                        THEN sol.price_subtotal / sol.product_uom_qty ELSE 0.0 END) AS amount_net_untaxed

                FROM stock_move sm
                JOIN sale_order_line sol ON sol.id = sm.sale_line_id
                JOIN sale_order so ON so.id = sol.order_id
                JOIN stock_picking sp ON sp.id = sm.picking_id
                JOIN stock_picking_type spt ON spt.id = sp.picking_type_id
                LEFT JOIN res_partner rp ON rp.id = so.partner_id
                LEFT JOIN product_product pp ON pp.id = sm.product_id
                LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
                LEFT JOIN move_return mr ON mr.move_id = sm.id
                WHERE sm.state = 'done'
                  AND spt.code = 'outgoing'
                  AND sm.sale_line_id IS NOT NULL
            )
        """)
