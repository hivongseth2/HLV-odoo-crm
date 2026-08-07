from odoo import api, fields, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    hlv_manual_avg_cost_enabled = fields.Boolean(
        string="HLV dùng giá vốn TB nhập tay",
        copy=False,
    )
    hlv_manual_avg_cost = fields.Float(
        string="HLV giá vốn TB nhập tay",
        digits="Product Price",
        copy=False,
    )
    report_group_line_ids = fields.One2many(
        'hlv.product.report.group.line',
        'product_id',
        string='Dòng nhóm báo cáo tồn kho',
    )
    report_group_ids = fields.Many2many(
        'hlv.product.report.group',
        string='Nhóm báo cáo tồn kho',
        compute='_compute_report_group_ids',
        search='_search_report_group_ids',
    )

    @api.depends('report_group_line_ids.group_id')
    def _compute_report_group_ids(self):
        for product in self:
            product.report_group_ids = product.report_group_line_ids.group_id

    def _search_report_group_ids(self, operator, value):
        return [('report_group_line_ids.group_id', operator, value)]
