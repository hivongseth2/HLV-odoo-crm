from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    report_group_ids = fields.Many2many(
        'hlv.product.report.group',
        string='Nhóm báo cáo tồn kho',
        compute='_compute_report_group_ids',
        search='_search_report_group_ids',
    )

    @api.depends('product_variant_ids.report_group_ids')
    def _compute_report_group_ids(self):
        for template in self:
            template.report_group_ids = template.product_variant_ids.report_group_ids

    def _search_report_group_ids(self, operator, value):
        return [('product_variant_ids.report_group_ids', operator, value)]
