from odoo import fields, models


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    sequence = fields.Integer(
        string='Thứ tự',
        default=10,
        help='Số thứ tự hiển thị trong dropdown menu in. Số nhỏ hơn xuất hiện trên cao hơn.',
    )

    _order = 'model ASC, sequence ASC, name ASC'

    def write(self, vals):
        result = super().write(vals)
        if 'sequence' in vals:
            # Xóa cache để dropdown in phản ánh thứ tự mới ngay lập tức
            self.env.registry.clear_cache()
        return result
