from odoo import api, fields, models, _
from markupsafe import Markup

class GoogleAdsAdsroidChatMessage(models.Model):
    _name = 'google.ads.adsroid.chat.message'
    _description = 'Lịch sử tin nhắn AI Adsroid'
    _order = 'create_date asc'

    campaign_id = fields.Many2one('google.ads.campaign', string='Chiến Dịch', ondelete='cascade', index=True)
    ad_id = fields.Many2one('google.ads.ad', string='Mẫu Quảng Cáo', ondelete='cascade', index=True)
    
    role = fields.Selection([
        ('user', 'Người dùng'),
        ('assistant', 'Adsroid AI'),
    ], string='Vai trò', required=True)
    
    content = fields.Text(string='Nội dung tin nhắn', required=True)
    content_html = fields.Html(string='Nội dung (HTML)', compute='_compute_content_html')

    @api.depends('content', 'role')
    def _compute_content_html(self):
        for rec in self:
            if rec.role == 'user':
                html = f"""
                    <div class="d-flex justify-content-end mb-2">
                        <div class="p-2 bg-primary text-white rounded-3 shadow-sm" style="max-width: 85%; white-space: pre-wrap;">
                            {rec.content}
                        </div>
                    </div>
                """
            else:
                html = f"""
                    <div class="d-flex justify-content-start mb-2">
                        <div class="p-2 bg-light border rounded-3 shadow-sm text-dark" style="max-width: 85%;">
                            <div class="fw-bold text-primary mb-1 small"><i class="fa fa-android"></i> Adsroid AI:</div>
                            <div style="white-space: pre-wrap;">{rec.content}</div>
                        </div>
                    </div>
                """
            rec.content_html = Markup(html)
