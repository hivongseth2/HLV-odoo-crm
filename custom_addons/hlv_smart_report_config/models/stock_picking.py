# -*- coding: utf-8 -*-
from odoo import models, api, _

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def action_smart_print(self):
        """
        In thẳng nếu chỉ có 1 quy tắc khớp.
        Mở wizard để chọn nếu có nhiều quy tắc khớp.
        Mở wizard rỗng nếu không tìm thấy quy tắc nào.
        """
        self.ensure_one()
        matched_rules = self.env['hlv.report.rule']._find_all_rules_for_picking(self)
        
        if len(matched_rules) == 1:
            rule = matched_rules[0]
            if rule.report_line_ids:
                # Chỉ 1 quy tắc → tạo wizard ngầm rồi in thẳng
                wizard = self.env['hlv.smart.print.wizard'].create({
                    'picking_id': self.id,
                    'partner_id': self.partner_id.id if self.partner_id else False,
                    'rule_id': rule.id,
                    'report_line_ids': [(0, 0, {
                        'report_id': line.report_id.id,
                        'copies': line.copies,
                    }) for line in rule.report_line_ids],
                })
                return {
                    'type': 'ir.actions.act_url',
                    'url': '/hlv_smart/print_merged/%s' % wizard.id,
                    'target': 'new',
                }
        
        if len(matched_rules) > 1:
            # Nhiều quy tắc cùng khớp → mở wizard để chọn
            return self._open_smart_print_wizard(matched_rules[0])
        
        # Không tìm thấy quy tắc nào → mở wizard thủ công
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
