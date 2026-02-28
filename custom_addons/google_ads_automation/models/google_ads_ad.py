from odoo import api, fields, models

class GoogleAdsAd(models.Model):
    _name = 'google.ads.ad'
    _description = 'Mẫu Quảng Cáo'

    name = fields.Char(string='Tên/Tiêu Đề Quảng Cáo')
    ad_group_id = fields.Many2one('google.ads.ad.group', string='Nhóm Quảng Cáo', required=True, ondelete='cascade')
    google_ad_id = fields.Char(string='Google Ad ID', required=True, index=True)

    status = fields.Selection([
        ('unspecified', 'Chưa xác định'),
        ('unknown', 'Không rõ'),
        ('enabled', 'Đang hoạt động'),
        ('paused', 'Tạm dừng'),
        ('removed', 'Đã xóa')
    ], string='Trạng Thái', default='unknown')

    type = fields.Char(string='Loại Quảng Cáo')
    final_urls = fields.Char(string='URL Đích (Final URL)')

    # Metrics
    clicks = fields.Integer(string='Lượt Nhấp', default=0)
    impressions = fields.Integer(string='Lượt Hiển Thị', default=0)
    cost = fields.Float(string='Chi Phí', default=0.0)
    conversions = fields.Float(string='Lượt Chuyển Đổi', default=0.0)

    _sql_constraints = [
        ('google_ad_id_uniq', 'unique(google_ad_id)', 'Google Ad ID phải là duy nhất!'),
    ]
