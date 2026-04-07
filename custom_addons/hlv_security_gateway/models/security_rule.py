from odoo import models, fields

class SecurityRule(models.Model):
    _name = 'hlv.security.rule'
    _description = 'HLV Security Rule'

    name = fields.Char(string='Description', required=True)
    rule_type = fields.Selection([
        ('ip', 'IP Address'),
        ('path', 'URL Path Pattern (Regex)'),
    ], string='Rule Type', required=True, default='ip')
    value = fields.Char(string='Value', required=True, help='IP or Regex pattern')
    active = fields.Boolean(default=True)
    action = fields.Selection([
        ('block', 'Block (403 Forbidden)'),
    ], string='Action', default='block')
