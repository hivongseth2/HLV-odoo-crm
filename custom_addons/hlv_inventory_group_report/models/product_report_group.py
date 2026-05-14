from odoo import models, fields, api


class HlvProductReportGroup(models.Model):
    _name = 'hlv.product.report.group'
    _description = 'Nhóm sản phẩm báo cáo tồn kho'
    _order = 'sequence, name'

    name = fields.Char('Tên nhóm', required=True)
    description = fields.Text('Mô tả')
    sequence = fields.Integer('Thứ tự', default=10)
    color = fields.Integer('Màu sắc')
    active = fields.Boolean('Hoạt động', default=True)

    product_ids = fields.Many2many(
        'product.product',
        'hlv_report_group_product_rel',
        'group_id',
        'product_id',
        string='Sản phẩm',
        domain=[('type', 'in', ['consu', 'product'])],
    )
    product_count = fields.Integer(
        'Số sản phẩm',
        compute='_compute_product_count',
        store=True,
    )

    @api.depends('product_ids')
    def _compute_product_count(self):
        for rec in self:
            rec.product_count = len(rec.product_ids)

    def action_open_report_wizard(self):
        """Open quick stock viewer pre-filled with this group."""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Tồn kho - ' + (self.name or ''),
            'res_model': 'hlv.stock.quick',
            'view_mode': 'form',
            'target': 'current',
            'context': {'default_group_id': self.id},
        }
