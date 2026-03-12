from odoo import fields, models


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    sequence = fields.Integer(
        string='Sequence',
        default=10,
        help='Sequence order for print templates. Lower numbers appear first in dropdown menu.',
    )

    _order = 'model ASC, sequence ASC, name ASC'
