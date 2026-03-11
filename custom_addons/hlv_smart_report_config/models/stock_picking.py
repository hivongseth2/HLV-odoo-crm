# -*- coding: utf-8 -*-
from odoo import models, api, _

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def action_smart_print(self):
        """Find matching rule and print, or show wizard if no rule found."""
        self.ensure_one()
        rule = self.env['hlv.report.rule']._find_rule_for_picking(self)
        
        if rule and rule.report_line_ids:
            return self._open_smart_print_wizard(rule)
        
        # No rule found or no reports in rule
        return self._open_smart_print_wizard()

    def _open_smart_print_wizard(self, rule=False):
        """Open the wizard with pre-filled rule if found."""
        action = self.env.ref('hlv_smart_report_config.action_hlv_smart_print_wizard').read()[0]
        context = dict(self.env.context)
        context.update({
            'default_picking_id': self.id,
            'default_partner_id': self.partner_id.id,
        })
        if rule:
            context.update({
                'default_rule_id': rule.id,
                'default_report_line_ids': [(0, 0, {
                    'report_id': line.report_id.id,
                    'copies': line.copies,
                }) for line in rule.report_line_ids],
            })
        action['context'] = context
        return action
