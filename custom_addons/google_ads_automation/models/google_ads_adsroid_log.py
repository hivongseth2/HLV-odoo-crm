from odoo import api, fields, models, _

class GoogleAdsAdsroidLog(models.Model):
    _name = 'google.ads.adsroid.log'
    _description = 'Lịch sử nhận định AI Adsroid'
    _order = 'create_date desc'

    campaign_id = fields.Many2one('google.ads.campaign', string='Chiến Dịch', ondelete='cascade')
    ad_id = fields.Many2one('google.ads.ad', string='Mẫu Quảng Cáo', ondelete='cascade')
    score = fields.Float(string='Điểm (Score)', help='Thang điểm đánh giá của AI (0-100)')
    suggested_action = fields.Selection([
        ('MAINTAIN', 'GIỮ NGUYÊN'),
        ('INCREASE_BUDGET', 'TĂNG NGÂN SÁCH'),
        ('DECREASE_BUDGET', 'GIẢM NGÂN SÁCH'),
        ('ADJUST_BUDGET', 'ĐIỀU CHỈNH NGÂN SÁCH'),
        ('PAUSE', 'TẠM DỪNG'),
        ('ENABLE', 'BẬT LẠI'),
        ('OPTIMIZE_CONTENT', 'TỐI ƯU NỘI DUNG'),
    ], string='Hành động đề xuất', required=True)
    insight = fields.Text(string='Nhận định (Insight)')
    is_applied = fields.Boolean(string='Đã tự động xử lý', default=False, readonly=True, help='Hệ thống đã tự động thực thi hành động này lên Google Ads.')
    
    # Optional formatting for UI
    action_label = fields.Char(compute='_compute_action_label')

    @api.depends('suggested_action')
    def _compute_action_label(self):
        selection = dict(self._fields['suggested_action'].selection)
        for rec in self:
            rec.action_label = selection.get(rec.suggested_action, rec.suggested_action)
