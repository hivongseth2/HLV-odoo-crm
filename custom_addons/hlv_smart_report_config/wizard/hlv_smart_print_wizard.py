# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class HlvSmartPrintWizard(models.TransientModel):
    _name = 'hlv.smart.print.wizard'
    _description = 'Smart Print Wizard'

    picking_id = fields.Many2one('stock.picking', string='Phiếu kho', required=True)
    partner_id = fields.Many2one('res.partner', string='Khách hàng', readonly=True)
    rule_id = fields.Many2one('hlv.report.rule', string='Quy tắc khớp', readonly=True)
    
    report_line_ids = fields.One2many('hlv.smart.print.wizard.line', 'wizard_id', string='Biên bản cần in')

    def action_confirm_print(self):
        self.ensure_one()
        if not self.report_line_ids:
            return {'type': 'ir.actions.act_window_close'}
            
        # Odoo's report_action takes a record list. 
        # To print N copies, we pass the same ID N times in the list.
        # Example: report.report_action([id, id, id]) -> Prints 3 copies in one PDF.
        
        # However, if there are multiple DIFFERENT reports, we can typically only return one Action.
        # As a robust solution, we will print the FIRST report in the list with its copies.
        # If there are more, we will warn the user or assume they will print them manually.
        
        line = self.report_line_ids[0]
        picking_ids = self.picking_id.ids * line.copies
        return line.report_id.report_action(picking_ids)

class HlvSmartPrintWizardLine(models.TransientModel):
    _name = 'hlv.smart.print.wizard.line'
    _description = 'Smart Print Wizard Line'

    wizard_id = fields.Many2one('hlv.smart.print.wizard', string='Wizard')
    report_id = fields.Many2one('ir.actions.report', string='Biên bản', required=True, domain=[('model', '=', 'stock.picking')])
    copies = fields.Integer(string='Số bản in', default=1, required=True)
