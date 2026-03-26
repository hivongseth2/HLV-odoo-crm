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
    def create_campaign(client, customer_id, vals):
        """Tạo campaign mới trên Google Ads"""
        try:
            # 1. Create a default budget FIRST if not provided
            budget_resource = vals.get('budget_resource_name')
            if not budget_resource:
                import time
                budget_service = client.get_service("CampaignBudgetService")
                budget_operation = client.get_type("CampaignBudgetOperation")
                budget = budget_operation.create
                budget.name = f"Budget for {vals.get('name')} - {int(time.time())}"
                budget.amount_micros = 50000000 # 50,000 default (micros base)
                budget.delivery_method = client.enums.BudgetDeliveryMethodEnum.STANDARD
                budget_response = budget_service.mutate_campaign_budgets(
                    customer_id=customer_id, operations=[budget_operation]
                )
                budget_resource = budget_response.results[0].resource_name

            # 2. Create the campaign
            campaign_service = client.get_service("CampaignService")
            campaign_operation = client.get_type("CampaignOperation")
            campaign = campaign_operation.create

            campaign.name = vals.get('name')
            campaign.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum[vals.get('channel_type', 'SEARCH')]
            campaign.status = client.enums.CampaignStatusEnum.PAUSED # Always start paused for safety
            
            # Budget handling
            campaign.campaign_budget = budget_resource

            # Bidding Strategy handling
            # Fix error: "The required field was not present: campaign_bidding_strategy"
            campaign.manual_cpc.enhanced_cpc_enabled = False

            # Network settings are required for Search campaigns
            if vals.get('channel_type', 'SEARCH') == 'SEARCH':
                campaign.network_settings.target_google_search = True
                campaign.network_settings.target_search_network = True
                campaign.network_settings.target_content_network = False
                campaign.network_settings.target_partner_search_network = False

            # Required fields for EU political advertising (mandatory since Sept 2025)
            # Must use the enum value, NOT a boolean
            campaign.contains_eu_political_advertising = (
                client.enums.EuPoliticalAdvertisingStatusEnum.DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING
            )
            
            # Shopping campaign requirements
            if vals.get('channel_type') == 'SHOPPING':
                campaign.shopping_setting.merchant_id = int(vals.get('merchant_center_id'))
                campaign.shopping_setting.campaign_priority = 0 # Low priority default

            response = campaign_service.mutate_campaigns(
                customer_id=customer_id,
                operations=[campaign_operation],
            )
            return True, response.results[0].resource_name
        except Exception as e:
            _logger.error("Create campaign failed: %s", str(e))
            return False, str(e)

    @staticmethod
    def find_campaign_by_name(client, customer_id, name):
        """Tìm Campaign ID theo tên trên Google Ads. Trả về resource_name hoặc None."""
        try:
            ga_service = client.get_service("GoogleAdsService")
            # Query tìm theo tên chính xác (phải dùng single quote cho chuỗi)
            # Chú ý: thoát dấu nháy đơn nếu tên có chứa nháy đơn
            safe_name = name.replace("'", "\\'")
            query = f"SELECT campaign.id, campaign.resource_name FROM campaign WHERE campaign.name = '{safe_name}' AND campaign.status != 'REMOVED' LIMIT 1"
            
            response = ga_service.search(customer_id=customer_id, query=query)
            for row in response:
                return row.campaign.resource_name
            return None
        except Exception as e:
            _logger.error("Find campaign by name '%s' failed: %s", name, str(e))
            return None

    @staticmethod
    def update_campaign(client, customer_id, campaign_resource_name, vals):
        """Cập nhật thông tin Campaign hiện có qua Google Ads Mutate API"""
        try:
            campaign_service = client.get_service("CampaignService")
            campaign_operation = client.get_type("CampaignOperation")
            campaign = campaign_operation.update
            campaign.resource_name = campaign_resource_name

            # Cập nhật Shopping settings nếu là loại SHOPPING
            mask_paths = []
            if 'name' in vals:
                campaign.name = vals['name']
                mask_paths.append('name')
            
            if vals.get('channel_type') == 'SHOPPING':
                if vals.get('merchant_center_id'):
                    campaign.shopping_setting.merchant_id = int(vals.get('merchant_center_id'))
                    mask_paths.append('shopping_setting.merchant_id')

            # Build field mask manually to avoid "Clear" and other method names being picked up
            # field_mask(None, campaign) can be problematic with proto-plus objects
            from google.protobuf.field_mask_pb2 import FieldMask
            campaign_operation.update_mask.CopyFrom(FieldMask(paths=mask_paths))

            response = campaign_service.mutate_campaigns(
                customer_id=customer_id,
                operations=[campaign_operation],
            )
            _logger.info("Campaign %s updated successfully.", campaign_resource_name)
            return True, response.results[0].resource_name
        except Exception as e:
            _logger.error("Update campaign %s failed: %s", campaign_resource_name, str(e))
            return False, str(e)

    @staticmethod
    def create_ad_group(client, customer_id, campaign_id, vals):
        """Tạo Ad Group trong một Campaign"""
        try:
            ad_group_service = client.get_service("AdGroupService")
            ad_group_operation = client.get_type("AdGroupOperation")
            ad_group = ad_group_operation.create

            ad_group.name = vals.get('name')
            ad_group.status = client.enums.AdGroupStatusEnum.ENABLED
            ad_group.campaign = client.get_service("CampaignService").campaign_path(customer_id, campaign_id)
            ad_group.type_ = client.enums.AdGroupTypeEnum.SEARCH_STANDARD

            response = ad_group_service.mutate_ad_groups(
                customer_id=customer_id,
                operations=[ad_group_operation],
            )
            return True, response.results[0].resource_name
        except Exception as e:
            _logger.error("Create ad group failed: %s", str(e))
            return False, str(e)

    @staticmethod
    def create_ad(client, customer_id, ad_group_id, vals):
        """Tạo Responsive Search Ad (RSA) trong một Ad Group"""
        try:
            ad_group_ad_service = client.get_service("AdGroupAdService")
            ad_group_ad_operation = client.get_type("AdGroupAdOperation")
            ad_group_ad = ad_group_ad_operation.create

            ad_group_ad.ad_group = client.get_service("AdGroupService").ad_group_path(customer_id, ad_group_id)
            ad_group_ad.status = client.enums.AdGroupAdStatusEnum.ENABLED
            
            ad = ad_group_ad.ad
            ad.final_urls.append(vals.get('final_url'))
            
            # Responsive Search Ad content
            rsa = ad.responsive_search_ad
            
            # Headline
            headline = client.get_type("AdTextAsset")
            headline.text = vals.get('headline')[:30] # Max 30 chars
            rsa.headlines.append(headline)
            
            # Description
            description = client.get_type("AdTextAsset")
            description.text = vals.get('description')[:90] # Max 90 chars
            rsa.descriptions.append(description)

            response = ad_group_ad_service.mutate_ad_group_ads(
                customer_id=customer_id,
                operations=[ad_group_ad_operation],
            )
            return True, response.results[0].resource_name
        except Exception as e:
            _logger.error("Create ad failed: %s", str(e))
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
