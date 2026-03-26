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
                # Lấy ngân sách từ Odoo (mặc định 50k) và đổi sang micros (x1.000.000)
                amount = vals.get('budget_amount', 50000.0)
                budget.amount_micros = int(amount * 1000000)
                budget.delivery_method = client.enums.BudgetDeliveryMethodEnum.STANDARD
                budget.explicitly_shared = False # Cần thiết cho PMax/Discovery
                budget_response = budget_service.mutate_campaign_budgets(
                    customer_id=customer_id, operations=[budget_operation]
                )
                budget_resource = budget_response.results[0].resource_name

            # 2. Create the campaign
            campaign_service = client.get_service("CampaignService")
            campaign_operation = client.get_type("CampaignOperation")
            campaign = campaign_operation.create

            campaign.name = vals.get('name')
            
            # Channel Type handling (Safe mapping)
            channel_type_raw = vals.get('channel_type', 'SEARCH')
            try:
                # Discovery (Khám phá) đã được đổi tên thành Demand Gen (Tạo nhu cầu) trong các phiên bản API mới
                if channel_type_raw == 'DISCOVERY':
                    if hasattr(client.enums.AdvertisingChannelTypeEnum, 'DEMAND_GEN'):
                        campaign.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.DEMAND_GEN
                    elif hasattr(client.enums.AdvertisingChannelTypeEnum, 'DISCOVERY'):
                        campaign.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.DISCOVERY
                    else:
                        campaign.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.SEARCH
                else:
                    campaign.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum[channel_type_raw]
            except (KeyError, AttributeError):
                _logger.warning("Loại kênh không hỗ trợ: %s. Tự động chuyển về SEARCH.", channel_type_raw)
                campaign.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.SEARCH

            campaign.status = client.enums.CampaignStatusEnum.PAUSED # Always start paused for safety
            
            # Final URL (Lading Page)
            if vals.get('final_url'):
                campaign.final_urls.append(vals.get('final_url'))

            # Budget handling
            campaign.campaign_budget = budget_resource

            # Bidding Strategy handling
            # Note: For some campaign types like VIDEO, creation via standard mutate is restricted.
            channel = vals.get('channel_type', 'SEARCH')
            if channel in ['PERFORMANCE_MAX', 'MULTI_CHANNEL', 'DISCOVERY']:
                # Modern types often require objective-based strategies
                campaign.maximize_conversions = {}
            else:
                # Default for Search/Display/Shopping
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

            # -- Performance Max (PMax) atomic creation (Campaign + Assets) --
            if vals.get('channel_type') == 'PERFORMANCE_MAX' and vals.get('business_name'):
                return GoogleAdsMutateService._create_pmax_campaign_atomic(client, customer_id, budget_resource, vals)

            response = campaign_service.mutate_campaigns(
                customer_id=customer_id,
                operations=[campaign_operation],
            )
            return True, response.results[0].resource_name
        except Exception as e:
            _logger.error("Create campaign failed: %s", str(e))
            return False, str(e)

    @staticmethod
    def _create_pmax_campaign_atomic(client, customer_id, budget_resource, vals):
        """Tạo PMax cùng lúc với Asset (Business Name) để thỏa mãn Brand Guidelines"""
        try:
            mutate_operations = []
            
            # 1. Tạo Asset Business Name
            asset_resource = GoogleAdsMutateService._create_business_name_asset(client, customer_id, vals.get('business_name'))
            
            # 2. Tạo Asset Logo nếu có
            logo_resource = None
            if vals.get('logo_image'):
                logo_resource = GoogleAdsMutateService._create_image_asset(client, customer_id, vals.get('logo_image'), "Logo")

            # -- Operation 1: Create Campaign (ID giả định -1) --
            op1 = client.get_type("MutateOperation")
            c = op1.campaign_operation.create
            temp_resource_name = f"customers/{customer_id}/campaigns/-1"
            c.resource_name = temp_resource_name
            c.name = vals.get('name')
            c.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.PERFORMANCE_MAX
            c.status = client.enums.CampaignStatusEnum.PAUSED
            c.campaign_budget = budget_resource
            c.maximize_conversions = {} 
            c.contains_eu_political_advertising = client.enums.EuPoliticalAdvertisingStatusEnum.DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING
            
            # PMax Final URLs
            if vals.get('final_url'):
                c.final_urls.append(vals.get('final_url'))

            mutate_operations.append(op1)

            # -- Operation 2: Link Business Name --
            op2 = client.get_type("MutateOperation")
            ca2 = op2.campaign_asset_operation.create
            ca2.campaign = temp_resource_name
            ca2.asset = asset_resource
            ca2.field_type = client.enums.AssetFieldTypeEnum.BUSINESS_NAME
            mutate_operations.append(op2)

            # -- Operation 3: Link Logo (nếu có) --
            if logo_resource:
                op3 = client.get_type("MutateOperation")
                ca3 = op3.campaign_asset_operation.create
                ca3.campaign = temp_resource_name
                ca3.asset = logo_resource
                ca3.field_type = client.enums.AssetFieldTypeEnum.LOGO
                mutate_operations.append(op3)

            google_ads_service = client.get_service("GoogleAdsService")
            response = google_ads_service.mutate(
                customer_id=customer_id,
                mutate_operations=mutate_operations
            )
            return True, response.mutate_operation_responses[0].campaign_result.resource_name

        except Exception as e:
            _logger.error("Atomic PMax creation failed: %s", str(e))
            return False, str(e)

    @staticmethod
    def _create_business_name_asset(client, customer_id, business_name):
        """Tạo asset loại BUSINESS_NAME"""
        asset_service = client.get_service("AssetService")
        operation = client.get_type("AssetOperation")
        asset = operation.create
        asset.business_name_asset.text = business_name
        response = asset_service.mutate_assets(customer_id=customer_id, operations=[operation])
        return response.results[0].resource_name

    @staticmethod
    def _create_image_asset(client, customer_id, image_base64, name):
        """Tạo Image Asset từ base64 Odoo"""
        import base64
        image_data = base64.b64decode(image_base64)
        
        asset_service = client.get_service("AssetService")
        operation = client.get_type("AssetOperation")
        asset = operation.create
        asset.name = f"{name} - {int(time.time())}"
        asset.type_ = client.enums.AssetTypeEnum.IMAGE
        asset.image_asset.data = image_data
        
        response = asset_service.mutate_assets(customer_id=customer_id, operations=[operation])
        return response.results[0].resource_name

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
