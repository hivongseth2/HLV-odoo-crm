# -*- coding: utf-8 -*-
import re
from odoo import models, fields, api, _

class HlvReportRule(models.Model):
    _name = 'hlv.report.rule'
    _description = 'Smart Report Print Rule'
    _order = 'sequence, id'

    name = fields.Char(string='Tên quy tắc', required=True, copy=False)
    active = fields.Boolean(string='Hoạt động', default=True)
    sequence = fields.Integer(string='Thứ tự', default=10)
    
    match_type = fields.Selection([
        ('partner', 'Khách hàng cụ thể'),
        ('regex', 'Regex tên khách hàng'),
        ('all', 'Mặc định (Tất cả)')
    ], string='Kiểu khớp', required=True, default='partner')
    
    partner_ids = fields.Many2many('res.partner', string='Khách hàng cụ thể', help="Quy tắc áp dụng nếu khách hàng trong danh sách này.")
    partner_regex = fields.Char(string='Regex tên khách hàng', help="Quy tắc áp dụng nếu tên khách hàng khớp với biểu thức này.")
    
    report_line_ids = fields.One2many('hlv.report.rule.line', 'rule_id', string='Biên bản cần in', copy=True)

    @api.model
    def _find_rule_for_picking(self, picking):
        """Find the first matching rule for a picking."""
        partner = picking.partner_id
        rules = self.search([('active', '=', True)], order='sequence, id')
        
        for rule in rules:
            if rule.match_type == 'all':
                return rule
            
            if not partner:
                continue
                
            if rule.match_type == 'partner':
                if partner.id in rule.partner_ids.ids:
                    return rule
            
            elif rule.match_type == 'regex' and rule.partner_regex:
                if re.search(rule.partner_regex, partner.display_name or '', re.IGNORECASE):
                    return rule
        
        return False

class HlvReportRuleLine(models.Model):
    _name = 'hlv.report.rule.line'
    _description = 'Report Rule Line'
    _order = 'sequence, id'

    rule_id = fields.Many2one('hlv.report.rule', string='Quy tắc', ondelete='cascade', required=True)
    sequence = fields.Integer(string='Thứ tự', default=10)
    report_id = fields.Many2one('ir.actions.report', string='Biên bản', required=True, domain=[('model', '=', 'stock.picking')])
    copies = fields.Integer(string='Số bản in', default=1, required=True)

    @api.constrains('copies')
    def _check_copies(self):
        for line in self:
            if line.copies < 1:
                raise ValueError(_("Số bản in phải ít nhất là 1."))
