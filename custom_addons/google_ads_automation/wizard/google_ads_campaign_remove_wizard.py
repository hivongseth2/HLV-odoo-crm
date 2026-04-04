from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class GoogleAdsCampaignRemoveWizard(models.TransientModel):
    _name = 'google.ads.campaign.remove.wizard'
    _description = 'Xác nhận xóa chiến dịch Google Ads'

    campaign_ids = fields.Many2many('google.ads.campaign', string='Chiến dịch')
    delete_on_google = fields.Boolean(
        string='Xóa vĩnh viễn trên Google Ads', 
        default=True,
        help='Nếu bật, hệ thống sẽ gọi API để xóa chiến dịch này trên Google Ads. '
             'Nếu tắt, chỉ xóa bản ghi trong Odoo.'
    )
    
    sync_state_info = fields.Text(compute='_compute_sync_state_info')

    @api.depends('campaign_ids')
    def _compute_sync_state_info(self):
        for rec in self:
            synced = rec.campaign_ids.filtered(lambda c: c.google_campaign_id)
            if synced:
                rec.sync_state_info = _("Phát hiện %s chiến dịch đã đồng bộ với Google Ads. "
                                        "Vui lòng xác nhận bạn có muốn gỡ bỏ chúng khỏi Google Ads không.") % len(synced)
            else:
                rec.sync_state_info = _("Các chiến dịch chọn chưa được đồng bộ với Google Ads (Nháp). "
                                        "Việc xóa sẽ chỉ diễn ra trong Odoo.")

    def action_confirm_remove(self):
        self.ensure_one()
        if not self.campaign_ids:
            return {'type': 'ir.actions.act_window_close'}

        synced_campaigns = self.campaign_ids.filtered(lambda c: c.google_campaign_id)
        
        if self.delete_on_google and synced_campaigns:
            # Thực hiện xóa trên Google Ads trước
            from ..services.google_ads_mutate import GoogleAdsMutateService
            
            for campaign in synced_campaigns:
                if campaign.account_id.state != 'authenticated' or campaign.account_id.is_demo:
                    _logger.info("Skip Google API delete for campaign %s (Demo or not authenticated)", campaign.id)
                    continue
                
                client = campaign.account_id._get_google_ads_client()
                customer_id = campaign.account_id.operating_customer_id
                
                ok, result = GoogleAdsMutateService.remove_campaign(
                    client, customer_id, campaign.google_campaign_id
                )
                if not ok:
                    _logger.error("Failed to delete campaign %s from Google Ads: %s", 
                                 campaign.google_campaign_id, result)
                    # Chúng ta vẫn tiếp tục xóa các campaign khác nếu một cái lỗi? 
                    # Hoặc ngừng? Ở đây tôi chọn log lỗi và tiếp tục để tránh kẹt.
        
        # Cuối cùng xóa bản ghi Odoo
        # Sử dụng context để bypass logic xóa tự động cũ (nếu có)
        return self.campaign_ids.with_context(confirm_google_deletion=True).unlink()
