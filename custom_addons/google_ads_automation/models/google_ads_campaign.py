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
        ('removed', 'Đã xóa'),
    ], string='Trạng Thái', default='unknown')

    channel_type = fields.Selection([
        ('SEARCH',          'Tìm Kiếm (Search)'),
        ('DISPLAY',         'Hiển Thị (Display)'),
        ('SHOPPING',        'Mua Sắm (Shopping)'),
        ('VIDEO',           'Video (YouTube)'),
        ('MULTI_CHANNEL',   'Đa Kênh (UAC)'),
        ('LOCAL',           'Địa Phương (Local)'),
        ('SMART',           'Thông Minh (Smart)'),
        ('PERFORMANCE_MAX', 'Tối Đa Hiệu Suất (PMax)'),
        ('DISCOVERY',       'Khám Phá (Discovery)'),
        ('HOTEL',           'Khách Sạn (Hotel)'),
        ('UNKNOWN',         'Không rõ'),
    ], string='Loại Kênh', help='Loại kênh quảng cáo từ Google Ads')

    # Metrics (Chỉ số hiệu suất cơ bản)
    clicks = fields.Integer(string='Lượt Nhấp', default=0)
    impressions = fields.Integer(string='Lượt Hiển Thị', default=0)
    cost = fields.Float(string='Chi Phí', default=0.0)
    conversions = fields.Float(string='Lượt Chuyển Đổi', default=0.0)

    # Computed Metrics for UI
    conversion_rate = fields.Float(
        string='Tỷ Lệ Chuyển Đổi (%)', 
        compute='_compute_performance_metrics', store=False
    )
    roas = fields.Float(
        string='ROAS', 
        compute='_compute_performance_metrics', store=False,
        help='Doanh thu / Chi phí. Lưu ý: Cần module tính doanh thu thực tế để chính xác, mặc định lấy Conversions * 500k / Cost'
    )
    
    @api.depends('clicks', 'conversions', 'cost')
    def _compute_performance_metrics(self):
        for rec in self:
            # Conversion Rate
            if rec.clicks > 0:
                rec.conversion_rate = (rec.conversions / rec.clicks) * 100
            else:
                rec.conversion_rate = 0.0
                
            # ROAS (Giả lập doanh thu trung bình 500k/đơn hàng nếu chưa link thực tế)
            # Nếu có link thực tế từ google_ads_conversion thì lấy sum doanh thu
            if rec.cost > 0:
                # Tìm doanh thu thực tế từ Conversion model
                conversions = self.env['google.ads.conversion'].search([('campaign_id', '=', rec.id)])
                if conversions:
                    total_revenue = sum(c.revenue for c in conversions)
                    rec.roas = total_revenue / rec.cost
                else:
                    # Giả định doanh thu 500k cho demo
                    rec.roas = (rec.conversions * 500000) / rec.cost
            else:
                rec.roas = 0.0

    _sql_constraints = [
        ('google_campaign_id_uniq', 'unique(google_campaign_id)', 'Google Campaign ID phải là duy nhất!'),
    ]
