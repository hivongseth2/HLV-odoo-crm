from odoo import fields, models

class GoogleAdsConversionAction(models.Model):
    _name = 'google.ads.conversion.action'
    _description = 'Hành động Chuyển đổi Google Ads'

    name = fields.Char(string='Tên Hành Động', required=True)
    google_conversion_id = fields.Char(string='Google Conversion ID', required=True)
    account_id = fields.Many2one('google.ads.account', string='Tài Khoản', required=True)
    type = fields.Selection([
        ('WEBPAGE', 'Trình duyệt (GTM)'),
        ('UPLOAD_CLICKS', 'Upload Offline (API)'),
    ], string='Loại', default='UPLOAD_CLICKS')
    active = fields.Boolean(default=True)
