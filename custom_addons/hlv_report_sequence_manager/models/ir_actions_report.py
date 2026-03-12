from odoo import api, fields, models


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
            self.env.registry.clear_cache()
        return result


class IrActionsActions(models.Model):
    _inherit = 'ir.actions.actions'

    @api.model
    def _get_bindings(self, model_name):
        result = super()._get_bindings(model_name)
        # Odoo builds toolbar via raw SQL ORDER BY id, ignoring _order.
        # Re-sort print actions by sequence so the dropdown reflects user-defined order.
        if result.get('print'):
            result['print'] = sorted(
                result['print'],
                key=lambda a: (a.get('sequence', 10), a.get('name', '')),
            )
        return result

