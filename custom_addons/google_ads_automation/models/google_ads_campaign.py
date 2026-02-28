from odoo import api, fields, models

class GoogleAdsCampaign(models.Model):
    _name = 'google.ads.campaign'
    _description = 'Google Ads Campaign'
    
    name = fields.Char(string='Campaign Name', required=True)
    account_id = fields.Many2one('google.ads.account', string='Google Ads Account', required=True, ondelete='cascade')
    google_campaign_id = fields.Char(string='Google Campaign ID', required=True, index=True)
    
    status = fields.Selection([
        ('unspecified', 'Unspecified'),
        ('unknown', 'Unknown'),
        ('enabled', 'Enabled'),
        ('paused', 'Paused'),
        ('removed', 'Removed')
    ], string='Status', default='unknown')
    
    channel_type = fields.Char(string='Channel Type', help='E.g., SEARCH, DISPLAY, PERFORMANCE_MAX')

    _sql_constraints = [
        ('google_campaign_id_uniq', 'unique(google_campaign_id)', 'Campaign ID must be unique!'),
    ]
