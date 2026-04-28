# -*- coding: utf-8 -*-
from odoo import _, models
from odoo.exceptions import UserError


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def report_action(self, docids, data=None, config=False):
        """Only allow printing stock pickings from outgoing pickings."""
        if self.model == 'stock.picking' and not self.env.context.get('allow_non_outgoing_print'):
            pickings = self.env['stock.picking'].browse(docids or [])
            if not pickings and self.env.context.get('active_model') == 'stock.picking':
                pickings = self.env['stock.picking'].browse(self.env.context.get('active_ids', []))

            if pickings:
                blocked = pickings.filtered(lambda p: p.picking_type_code != 'outgoing')
                if blocked:
                    raise UserError(_(
                        'Chi duoc phep in tren phieu xuat kho (Outgoing). '
                        'Vui long in tu phieu xuat kho chinh.'
                    ))

        return super().report_action(docids, data=data, config=config)
