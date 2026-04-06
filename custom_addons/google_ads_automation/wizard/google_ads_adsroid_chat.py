from odoo import api, fields, models, _
from odoo.exceptions import UserError
from markupsafe import Markup

class GoogleAdsAdsroidChat(models.TransientModel):
    _name = 'google.ads.adsroid.chat'
    _description = 'Adsroid AI Chat Assistant'

    campaign_id = fields.Many2one('google.ads.campaign', string='Chiến Dịch', required=True)
    user_query = fields.Text(string='Câu hỏi của bạn')
    chat_history = fields.Html(string='Nội dung trò chuyện', compute='_compute_chat_history')

    @api.depends('campaign_id')
    def _compute_chat_history(self):
        for rec in self:
            messages = self.env['google.ads.adsroid.chat.message'].search([
                ('campaign_id', '=', rec.campaign_id.id)
            ], limit=50) # Tải 50 tin nhắn gần nhất
            
            html_parts = []
            for msg in messages:
                html_parts.append(msg.content_html)
            
            rec.chat_history = Markup("").join(html_parts)

    def action_send_message(self):
        self.ensure_one()
        if not self.user_query:
            return self._reopen_self()

        # 1. Lưu tin nhắn của User
        self.env['google.ads.adsroid.chat.message'].create({
            'campaign_id': self.campaign_id.id,
            'role': 'user',
            'content': self.user_query,
        })

        cam = self.campaign_id
        # Chuẩn bị dữ liệu context cho AI
        campaign_data = {
            "id": cam.google_campaign_id,
            "name": cam.name,
            "status": cam.status,
            "metrics": {
                "clicks": cam.clicks,
                "cost": cam.cost,
                "conversions": cam.conversions,
                "roas": cam.roas,
                "budget": cam.budget_amount,
                "impression_share": cam.search_impression_share,
                "lost_is_rank": cam.search_rank_lost_impression_share,
                "lost_is_budget": cam.search_budget_lost_impression_share,
            }
        }
        
        from ..services.adsroid_api import AdsroidApiService
        success, result = AdsroidApiService.analyze_campaign(
            cam.account_id.adsroid_api_key,
            cam.account_id.adsroid_organisation_id,
            cam.account_id.adsroid_project_id,
            campaign_data,
            [], # Product data empty for speed in chat
            is_demo=cam.account_id.is_demo,
            user_query=self.user_query
        )

        if success:
            ai_insight = result.get('insight', '')
            
            # 2. Lưu tin nhắn của AI
            self.env['google.ads.adsroid.chat.message'].create({
                'campaign_id': self.campaign_id.id,
                'role': 'assistant',
                'content': ai_insight,
            })
            
            self.user_query = "" # Reset query
            return self._reopen_self()
        else:
            raise UserError(_("Adsroid gặp lỗi: %s") % result)

    def _reopen_self(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'google.ads.adsroid.chat',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }
