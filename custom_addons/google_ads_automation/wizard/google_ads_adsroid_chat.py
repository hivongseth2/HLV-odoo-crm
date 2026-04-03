from odoo import api, fields, models, _
from odoo.exceptions import UserError
from markupsafe import Markup

class GoogleAdsAdsroidChat(models.TransientModel):
    _name = 'google.ads.adsroid.chat'
    _description = 'Adsroid AI Chat Assistant'

    campaign_id = fields.Many2one('google.ads.campaign', string='Chiến Dịch', required=True)
    user_query = fields.Text(string='Câu hỏi của bạn')
    chat_history = fields.Html(string='Nội dung trò chuyện', readonly=True, default='')

    def action_send_message(self):
        self.ensure_one()
        if not self.user_query:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'google.ads.adsroid.chat',
                'res_id': self.id,
                'view_mode': 'form',
                'target': 'new',
            }

        cam = self.campaign_id
        # Chuẩn bị dữ liệu context
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
            }
        }
        product_data = []
        for line in cam.feed_line_ids:
            product_data.append({
                "product_code": line.product_id.default_code,
                "qty_available": line.qty_available,
                "stock_status": line.stock_status,
            })

        from ..services.adsroid_api import AdsroidApiService
        success, result = AdsroidApiService.analyze_campaign(
            cam.account_id.adsroid_api_key,
            cam.account_id.adsroid_organisation_id,
            cam.account_id.adsroid_project_id,
            campaign_data,
            product_data,
            is_demo=cam.account_id.is_demo,
            user_query=self.user_query
        )

        if success:
            ai_insight = result.get('insight', '')
            
            # Cập nhật lịch sử chat theo phong cách hiện đại
            new_history = f"""
                <div class="mb-3 text-end">
                    <div class="d-inline-block p-2 bg-primary text-white rounded-3 shadow-sm" style="max-width: 80%;">
                        {self.user_query}
                    </div>
                </div>
                <div class="mb-3 text-start">
                    <div class="d-inline-block p-2 bg-light border rounded-3 shadow-sm" style="max-width: 80%;">
                        <div class="fw-bold text-primary mb-1"><i class="fa fa-android"></i> Adsroid AI:</div>
                        {ai_insight}
                    </div>
                </div>
            """
            self.chat_history = Markup(self.chat_history or "") + Markup(new_history)
            self.user_query = "" # Reset query for next turn

            # Nếu AI đề xuất thay đổi cụ thể và có budget mới
            if result.get('suggested_action') == 'ADJUST_BUDGET' and result.get('new_budget'):
                # Lưu vào log chiến dịch để người dùng biết AI có đề xuất
                log_msg = _("Adsroid đề xuất trong Chat: Điều chỉnh ngân sách thành %s (Lý do: %s)") % (
                    f"{result['new_budget']:,}đ", ai_insight
                )
                cam.message_post(body=log_msg)

            return {
                'type': 'ir.actions.act_window',
                'res_model': 'google.ads.adsroid.chat',
                'res_id': self.id,
                'view_mode': 'form',
                'target': 'new',
            }
        else:
            raise UserError(_("Adsroid gặp lỗi: %s") % result)
