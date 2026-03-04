"""
Google Ads Mutate Service
─────────────────────────
Utility layer gọi Google Ads API để thực hiện hành động thực tế
(pause, enable, update budget) trên nền tảng Google.
"""
from odoo.exceptions import UserError
from odoo import _
import logging

_logger = logging.getLogger(__name__)

try:
    from google.ads.googleads.client import GoogleAdsClient
    from google.ads.googleads.errors import GoogleAdsException
except ImportError:
    GoogleAdsClient = None
    GoogleAdsException = None


class GoogleAdsMutateService:
    """Stateless service — nhận client + IDs, trả về kết quả"""

    @staticmethod
    def pause_campaign(client, customer_id, campaign_id):
        """Tạm dừng campaign trên Google Ads"""
        return GoogleAdsMutateService._update_campaign_status(
            client, customer_id, campaign_id, 'PAUSED'
        )

    @staticmethod
    def enable_campaign(client, customer_id, campaign_id):
        """Bật lại campaign trên Google Ads"""
        return GoogleAdsMutateService._update_campaign_status(
            client, customer_id, campaign_id, 'ENABLED'
        )

    @staticmethod
    def _update_campaign_status(client, customer_id, campaign_id, new_status):
        """Cập nhật trạng thái Campaign qua Google Ads Mutate API"""
        try:
            campaign_service = client.get_service("CampaignService")
            campaign_operation = client.get_type("CampaignOperation")

            campaign = campaign_operation.update
            campaign.resource_name = campaign_service.campaign_path(
                customer_id, campaign_id
            )

            # Set status
            status_enum = client.enums.CampaignStatusEnum
            campaign.status = getattr(status_enum, new_status)

            # Field mask
            from google.api_core.protobuf_helpers import field_mask
            campaign_operation.update_mask = field_mask(None, campaign)

            response = campaign_service.mutate_campaigns(
                customer_id=customer_id,
                operations=[campaign_operation],
            )
            _logger.info(
                "Campaign %s status updated to %s. Resource: %s",
                campaign_id, new_status,
                response.results[0].resource_name,
            )
            return True, response.results[0].resource_name

        except Exception as e:
            _logger.error("Mutate campaign %s failed: %s", campaign_id, str(e))
            return False, str(e)

    @staticmethod
    def update_campaign_budget(client, customer_id, campaign_resource_name, new_budget_micros):
        """Cập nhật budget cho campaign
        
        Note: Google Ads quản lý budget qua CampaignBudget resource riêng,
        không trực tiếp trên Campaign. Logic đầy đủ cần GAQL query lấy
        budget resource name trước rồi mutate.
        Đây là placeholder — sẽ implement đầy đủ khi có tài khoản thật để test.
        """
        _logger.warning(
            "update_campaign_budget chưa implement đầy đủ. "
            "campaign=%s, new_budget=%s micros",
            campaign_resource_name, new_budget_micros,
        )
        return False, "Chưa implement — cần test với tài khoản thật"
