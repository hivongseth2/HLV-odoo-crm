from odoo import models, fields, api


class HlvStockQuick(models.TransientModel):
    _name = 'hlv.stock.quick'
    _description = 'Xem tồn kho theo nhóm'

    group_id = fields.Many2one(
        'hlv.product.report.group',
        string='Nhóm sản phẩm',
        required=True,
    )
    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Kho hàng',
        help='Để trống = cộng tất cả các kho',
    )
    show_zero = fields.Boolean('Hiện SP hết hàng', default=False)

    line_ids = fields.One2many('hlv.stock.quick.line', 'report_id', string='Sản phẩm')

    total_qty = fields.Float('Tổng tồn kho', compute='_compute_total')

    @api.depends('line_ids.qty')
    def _compute_total(self):
        for rec in self:
            rec.total_qty = sum(rec.line_ids.mapped('qty'))

    @api.onchange('group_id', 'warehouse_id', 'show_zero')
    def _onchange_refresh(self):
        self._populate_lines()

    def _populate_lines(self):
        self.line_ids = [(5, 0, 0)]
        if not self.group_id:
            return
        lines = []
        for product in self.group_id.product_ids.sorted('default_code'):
            if self.warehouse_id:
                qty = product.with_context(warehouse=self.warehouse_id.id).qty_available
            else:
                qty = product.qty_available
            if not self.show_zero and qty == 0:
                continue
            lines.append((0, 0, {
                'product_code': product.default_code or '',
                'product_name': product.name,
                'qty': qty,
            }))
        self.line_ids = lines


class HlvStockQuickLine(models.TransientModel):
    _name = 'hlv.stock.quick.line'
    _description = 'Dòng tồn kho nhanh'
    _order = 'product_code, product_name'

    report_id = fields.Many2one('hlv.stock.quick', required=True, ondelete='cascade')
    product_code = fields.Char('Mã SP')
    product_name = fields.Char('Tên sản phẩm')
    qty = fields.Float('Tồn kho')
