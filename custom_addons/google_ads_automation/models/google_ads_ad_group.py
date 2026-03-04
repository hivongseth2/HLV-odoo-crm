from odoo import api, fields, models

class GoogleAdsAdGroup(models.Model):
    _name = 'google.ads.ad.group'
    _description = 'Nhóm Quảng Cáo'

    name = fields.Char(string='Tên Nhóm Quảng Cáo', required=True)
    campaign_id = fields.Many2one('google.ads.campaign', string='Chiến Dịch', required=True, ondelete='cascade')
    google_ad_group_id = fields.Char(string='Google Ad Group ID', required=True, index=True)

    status = fields.Selection([
        ('unspecified', 'Chưa xác định'),
        ('unknown', 'Không rõ'),
        ('enabled', 'Đang hoạt động'),
        ('paused', 'Tạm dừng'),
        ('removed', 'Đã xóa'),
    ], string='Trạng Thái', default='unknown')

    type = fields.Selection([
        ('SEARCH_STANDARD',         'Tìm Kiếm Chuẩn'),
        ('SEARCH_DYNAMIC_ADS',      'Tìm Kiếm Động (DSA)'),
        ('DISPLAY_STANDARD',        'Hiển Thị Chuẩn'),
        ('SHOPPING_PRODUCT_ADS',    'Mua Sắm — Sản Phẩm'),
        ('SHOPPING_SMART_ADS',      'Mua Sắm Thông Minh'),
        ('VIDEO_TRUE_VIEW_IN_STREAM', 'Video In-Stream'),
        ('VIDEO_BUMPER',            'Video Bumper (6 giây)'),
        ('VIDEO_OUTSTREAM',         'Video Outstream'),
        ('HOTEL_ADS',               'Khách Sạn'),
        ('DISCOVERY',               'Khám Phá'),
        ('UNKNOWN',                 'Không rõ'),
    ], string='Loại Nhóm Quảng Cáo')

    # Metrics
    clicks = fields.Integer(string='Lượt Nhấp', default=0)
    impressions = fields.Integer(string='Lượt Hiển Thị', default=0)
    cost = fields.Float(string='Chi Phí', default=0.0)
    conversions = fields.Float(string='Lượt Chuyển Đổi', default=0.0)

    _sql_constraints = [
        ('google_ad_group_id_uniq', 'unique(google_ad_group_id)', 'Google Ad Group ID phải là duy nhất!'),
    ]
