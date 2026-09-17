from odoo import api, fields, models


class SaleOrder(models.Model):
    """Đơn bán có thể được xếp vào kế hoạch giao từ trước khi kho soạn hàng."""

    _inherit = 'sale.order'

    vtracking_plan_line_ids = fields.One2many(
        'hlv.vtracking.plan.line', 'sale_order_id', string='Dòng kế hoạch giao',
    )
    vtracking_plan_id = fields.Many2one(
        'hlv.vtracking.plan', string='Kế hoạch giao', compute='_compute_vtracking_plan_id',
        store=True,
        help='Kế hoạch đang chứa đơn này khi chưa có phiếu xuất. Khi phiếu ra đời, dòng kế '
             'hoạch chuyển sang trỏ vào phiếu.',
    )

    @api.depends('vtracking_plan_line_ids', 'vtracking_plan_line_ids.plan_id')
    def _compute_vtracking_plan_id(self):
        for order in self:
            order.vtracking_plan_id = order.vtracking_plan_line_ids[:1].plan_id
