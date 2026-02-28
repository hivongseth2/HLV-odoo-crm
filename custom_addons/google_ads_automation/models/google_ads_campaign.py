from odoo import api, fields, models

class GoogleAdsCampaign(models.Model):
    _name = 'google.ads.campaign'
    _description = 'Chiến dịch Google Ads'
    
    name = fields.Char(string='Tên Chiến Dịch', required=True)
    account_id = fields.Many2one('google.ads.account', string='Tài Khoản Google Ads', required=True, ondelete='cascade')
    google_campaign_id = fields.Char(string='Google Campaign ID', required=True, index=True)
    
    status = fields.Selection([
        ('unspecified', 'Chưa xác định'),
        ('unknown', 'Không rõ'),
        ('enabled', 'Đang hoạt động'),
        ('paused', 'Tạm dừng'),
        ('removed', 'Đã xóa')
    ], string='Trạng Thái', default='unknown')
    
    channel_type = fields.Char(string='Loại Kênh', help='VD: SEARCH, DISPLAY, PERFORMANCE_MAX')

    # Metrics (Chỉ số hiệu suất cơ bản)
    clicks = fields.Integer(string='Lượt Nhấp (Clicks)', default=0)
    impressions = fields.Integer(string='Lượt Hiển Thị (Impressions)', default=0)
    cost = fields.Float(string='Chi Phí (Cost)', default=0.0)
    conversions = fields.Float(string='Lượt Chuyển Đổi (Conversions)', default=0.0)

    _sql_constraints = [
        ('google_campaign_id_uniq', 'unique(google_campaign_id)', 'Google Campaign ID phải là duy nhất!'),
    ]
