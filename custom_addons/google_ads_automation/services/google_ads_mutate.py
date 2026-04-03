"""
Google Ads Mutate Service
─────────────────────────
Utility layer gọi Google Ads API để thực hiện hành động thực tế
(pause, enable, update budget) trên nền tảng Google.
"""
from odoo.exceptions import UserError
from odoo import _
import logging
import time

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

            # Field mask manually
            from google.protobuf.field_mask_pb2 import FieldMask
            mask_paths = ['status']
            campaign_operation.update_mask.CopyFrom(FieldMask(paths=mask_paths))

            response = campaign_service.mutate_campaigns(
                customer_id=customer_id,
                operations=[campaign_operation],
            )
            return True, response.results[0].resource_name
        except Exception as e:
            _logger.error("Mutate campaign %s failed: %s", campaign_id, str(e))
            return False, str(e)

    @staticmethod
    def pause_ad_group(client, customer_id, ad_group_id):
        return GoogleAdsMutateService._update_ad_group_status(client, customer_id, ad_group_id, 'PAUSED')

    @staticmethod
    def enable_ad_group(client, customer_id, ad_group_id):
        return GoogleAdsMutateService._update_ad_group_status(client, customer_id, ad_group_id, 'ENABLED')

    @staticmethod
    def _update_ad_group_status(client, customer_id, ad_group_id, new_status):
        try:
            service = client.get_service("AdGroupService")
            operation = client.get_type("AdGroupOperation")
            ag = operation.update
            ag.resource_name = service.ad_group_path(customer_id, ad_group_id)
            ag.status = client.enums.AdGroupStatusEnum[new_status]

            from google.protobuf.field_mask_pb2 import FieldMask
            mask_paths = ['status']
            operation.update_mask.CopyFrom(FieldMask(paths=mask_paths))

            response = service.mutate_ad_groups(customer_id=customer_id, operations=[operation])
            return True, response.results[0].resource_name
        except Exception as e:
            _logger.error("Mutate ad group %s to %s failed: %s", ad_group_id, new_status, str(e))
            return False, str(e)

    @staticmethod
    def pause_ad(client, customer_id, ad_group_id, ad_id):
        return GoogleAdsMutateService._update_ad_status(client, customer_id, ad_group_id, ad_id, 'PAUSED')

    @staticmethod
    def enable_ad(client, customer_id, ad_group_id, ad_id):
        return GoogleAdsMutateService._update_ad_status(client, customer_id, ad_group_id, ad_id, 'ENABLED')

    @staticmethod
    def _update_ad_status(client, customer_id, ad_group_id, ad_id, new_status):
        try:
            # Normalize ad_id (handle composite G~A case)
            pure_ad_id = str(ad_id).split('~')[-1]
            service = client.get_service("AdGroupAdService")
            operation = client.get_type("AdGroupAdOperation")
            ad_group_ad = operation.update
            ad_group_ad.resource_name = f"customers/{customer_id}/adGroupAds/{ad_group_id}~{pure_ad_id}"
            ad_group_ad.status = client.enums.AdGroupAdStatusEnum[new_status]

            from google.protobuf.field_mask_pb2 import FieldMask
            mask_paths = ['status']
            operation.update_mask.CopyFrom(FieldMask(paths=mask_paths))

            response = service.mutate_ad_group_ads(customer_id=customer_id, operations=[operation])
            return True, response.results[0].resource_name
        except Exception as e:
            _logger.error("Mutate ad %s to %s failed: %s", ad_id, new_status, str(e))
            return False, str(e)

    @staticmethod
    def create_campaign(client, customer_id, vals):
        """Tạo campaign mới trên Google Ads"""
        try:
            # 1. Create a default budget FIRST if not provided
            budget_resource = vals.get('budget_resource_name')
            if not budget_resource:
                budget_service = client.get_service("CampaignBudgetService")
                budget_operation = client.get_type("CampaignBudgetOperation")
                budget = budget_operation.create
                budget.name = f"Budget for {vals.get('name')} - {int(time.time())}"
                # Lấy ngân sách từ Odoo (mặc định 50k) và đổi sang micros (x1.000.000)
                amount = vals.get('budget_amount', 50000.0)
                budget.amount_micros = int(amount * 1000000)
                budget.delivery_method = client.enums.BudgetDeliveryMethodEnum.STANDARD
                budget.explicitly_shared = False # Cần thiết cho PMax/Discovery/Smart
                
                # Special handling for Smart Campaigns (Express context)
                if vals.get('channel_type') == 'SMART':
                    if hasattr(client.enums.BudgetTypeEnum, 'SMART_CAMPAIGN'):
                        budget.type_ = client.enums.BudgetTypeEnum.SMART_CAMPAIGN
                    else:
                        _logger.warning("BudgetTypeEnum.SMART_CAMPAIGN not found, skipping specific budget type.")

                budget_response = budget_service.mutate_campaign_budgets(
                    customer_id=customer_id, operations=[budget_operation]
                )
                budget_resource = budget_response.results[0].resource_name

            # 2. Create the campaign
            campaign_service = client.get_service("CampaignService")
            campaign_operation = client.get_type("CampaignOperation")
            campaign = campaign_operation.create

            campaign.name = str(vals.get('name') or "Unnamed Campaign")
            
            # Channel Type handling (Safe mapping)
            channel_type_raw = str(vals.get('channel_type', 'SEARCH')).upper()
            try:
                # Discovery (Khám phá) đã được đổi tên thành Demand Gen (Tạo nhu cầu) trong các phiên bản API mới
                if channel_type_raw in ['DISCOVERY', 'DEMAND_GEN']:
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

            # Channel Sub Type handling (Required for some types like MULTI_CHANNEL or VIDEO)
            channel_sub_type_raw = vals.get('channel_sub_type')
            if channel_sub_type_raw:
                try:
                    campaign.advertising_channel_sub_type = client.enums.AdvertisingChannelSubTypeEnum[channel_sub_type_raw]
                except (KeyError, AttributeError):
                    _logger.warning("Loại hình phụ không hỗ trợ: %s", channel_sub_type_raw)

            campaign.status = client.enums.CampaignStatusEnum.PAUSED # Always start paused for safety
            
            # Note: Final URL is typically set at Ad level or Asset group level, not Campaign level.
            # Removing redundant assignment that causes API error.

            # Budget handling
            campaign.campaign_budget = str(budget_resource)

            # Bidding Strategy handling
            # Note: For some campaign types like VIDEO, creation via standard mutate is restricted or has specific rules.
            channel = vals.get('channel_type', 'SEARCH')
            if channel in ['PERFORMANCE_MAX', 'MULTI_CHANNEL', 'DISCOVERY']:
                # Modern types often require objective-based strategies
                campaign.maximize_conversions = {}
                
                # Special handling for App Campaign (MULTI_CHANNEL)
                if channel == 'MULTI_CHANNEL':
                    # 1. App Campaign Setting is REQUIRED
                    app_setting = client.get_type("AppCampaignSetting")
                    app_setting.app_id = str(vals.get('app_id') or "")
                    app_setting.app_store = client.enums.AppCampaignAppStoreEnum[vals.get('app_store', 'GOOGLE_APP_STORE')]
                    app_setting.bidding_strategy_goal_type = client.enums.AppCampaignBiddingStrategyGoalTypeEnum[vals.get('app_bidding_goal', 'OPTIMIZE_INSTALLS_TARGET_INSTALL_COST')]
                    campaign.app_campaign_setting = app_setting
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
        """Tạo PMax nguyên tử duy nhất (Atomic) để thỏa mãn Brand Guidelines"""
        try:
            google_ads_service = client.get_service("GoogleAdsService")
            mutate_operations = []
            
            # -- Tạo các Asset thô trước --
            asset_resource = GoogleAdsMutateService._create_business_name_asset(client, customer_id, vals.get('business_name'))
            logo_resource = None
            if vals.get('logo_image'):
                logo_resource = GoogleAdsMutateService._create_image_asset(client, customer_id, vals.get('logo_image'), "Logo", target_ratio=1.0)
            
            marketing_resource = None
            if vals.get('marketing_image'):
                marketing_resource = GoogleAdsMutateService._create_image_asset(client, customer_id, vals.get('marketing_image'), "Marketing Landscape", target_ratio=1.91)
            elif vals.get('logo_image'):
                marketing_resource = GoogleAdsMutateService._create_image_asset(client, customer_id, vals.get('logo_image'), "Marketing Landscape (Auto)", target_ratio=1.91)
            square_mkt_resource = logo_resource

            h1 = GoogleAdsMutateService._create_text_asset(client, customer_id, vals.get('pmax_headline_1') or vals.get('name')[:30])
            h2 = GoogleAdsMutateService._create_text_asset(client, customer_id, vals.get('pmax_headline_2') or f"Khám phá {vals.get('name')}"[:30])
            h3 = GoogleAdsMutateService._create_text_asset(client, customer_id, vals.get('pmax_headline_3') or "Mua ngay hôm nay"[:30])
            lh1 = GoogleAdsMutateService._create_text_asset(client, customer_id, vals.get('pmax_long_headline') or f"{vals.get('name')} - Sự lựa chọn hoàn hảo."[:90])
            d1 = GoogleAdsMutateService._create_text_asset(client, customer_id, vals.get('pmax_description_1') or f"Dịch vụ chất lượng cao từ {vals.get('name')}."[:90])
            d2 = GoogleAdsMutateService._create_text_asset(client, customer_id, vals.get('pmax_description_2') or "Đăng ký nhận ưu đãi ngay."[:90])

            # -- 1. Tạo Chiến dịch (ID tạm -1) --
            op_c = client.get_type("MutateOperation")
            c = op_c.campaign_operation.create
            temp_campaign_resource = f"customers/{customer_id}/campaigns/-1"
            c.resource_name = temp_campaign_resource
            c.name = vals.get('name')
            c.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.PERFORMANCE_MAX
            c.status = client.enums.CampaignStatusEnum.PAUSED
            c.campaign_budget = budget_resource
            c.maximize_conversions = {} 
            c.contains_eu_political_advertising = client.enums.EuPoliticalAdvertisingStatusEnum.DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING
            
            # Kích hoạt Brand Guidelines (Sử dụng thuộc tính trực tiếp)
            try:
                c.performance_max_setting.brand_guidelines_enabled = True
            except:
                try: c.performance_max_settings.brand_guidelines_enabled = True
                except: pass
            
            mutate_operations.append(op_c)

            # -- 2. Liên kết Brand Assets vào Campaign - BẮT BUỘC cho Brand Guidelines --
            if asset_resource:
                op = client.get_type("MutateOperation")
                ca = op.campaign_asset_operation.create
                ca.campaign = temp_campaign_resource
                ca.asset = asset_resource
                ca.field_type = client.enums.AssetFieldTypeEnum.BUSINESS_NAME
                mutate_operations.append(op)
            
            if logo_resource:
                op = client.get_type("MutateOperation")
                ca = op.campaign_asset_operation.create
                ca.campaign = temp_campaign_resource
                ca.asset = logo_resource
                ca.field_type = client.enums.AssetFieldTypeEnum.LOGO
                mutate_operations.append(op)

            # -- 3. Tạo Nhóm thành phần (ID tạm -2) --
            op_ag = client.get_type("MutateOperation")
            ag = op_ag.asset_group_operation.create
            temp_asset_group_resource = f"customers/{customer_id}/assetGroups/-2"
            ag.resource_name = temp_asset_group_resource
            ag.name = f"Nhóm 1 - {vals.get('name')}"
            ag.campaign = temp_campaign_resource
            ag.status = client.enums.AssetGroupStatusEnum.ENABLED
            
            f_url = vals.get('final_url')
            if f_url:
                if not f_url.startswith('http'): f_url = 'https://' + f_url
                ag.final_urls.append(f_url)
            else:
                ag.final_urls.append("https://google.com")
            mutate_operations.append(op_ag)

            # -- 4. Liên kết assets vào Nhóm thành phần --
            def add_ag_link(asset_res, field_type):
                if not asset_res: return
                op = client.get_type("MutateOperation")
                aga = op.asset_group_asset_operation.create
                aga.asset_group = temp_asset_group_resource
                aga.asset = asset_res
                aga.field_type = field_type
                mutate_operations.append(op)

            # Theo guidelines, khi đã link CampaignAsset thì trong AssetGroup KHÔNG CẦN BN/Logo nữa
            add_ag_link(marketing_resource, client.enums.AssetFieldTypeEnum.MARKETING_IMAGE)
            add_ag_link(square_mkt_resource, client.enums.AssetFieldTypeEnum.SQUARE_MARKETING_IMAGE)
            add_ag_link(h1, client.enums.AssetFieldTypeEnum.HEADLINE)
            add_ag_link(h2, client.enums.AssetFieldTypeEnum.HEADLINE)
            add_ag_link(h3, client.enums.AssetFieldTypeEnum.HEADLINE)
            add_ag_link(lh1, client.enums.AssetFieldTypeEnum.LONG_HEADLINE)
            add_ag_link(d1, client.enums.AssetFieldTypeEnum.DESCRIPTION)
            add_ag_link(d2, client.enums.AssetFieldTypeEnum.DESCRIPTION)

            # Gửi duy nhất 1 mutate Atomic
            response = google_ads_service.mutate(customer_id=customer_id, mutate_operations=mutate_operations)
            real_resource = response.mutate_operation_responses[0].campaign_result.resource_name
            _logger.info("Đồng bộ Atomic PMax thành công: %s", real_resource)
            
            return True, real_resource

        except Exception as e:
            _logger.error("Atomic PMax creation failed: %s", str(e))
            return False, str(e)

    @staticmethod
    def _create_text_asset(client, customer_id, text):
        """Tạo asset loại TEXT (cho Headline/Description)"""
        if not text: return None
        asset_service = client.get_service("AssetService")
        operation = client.get_type("AssetOperation")
        asset = operation.create
        asset.type_ = client.enums.AssetTypeEnum.TEXT
        asset.text_asset.text = text
        response = asset_service.mutate_assets(customer_id=customer_id, operations=[operation])
        return response.results[0].resource_name

    @staticmethod
    def _create_business_name_asset(client, customer_id, business_name):
        """Tạo asset loại BUSINESS_NAME (Tự động nhận diện Enum theo phiên bản API)"""
        if not business_name: return None
        asset_service = client.get_service("AssetService")
        operation = client.get_type("AssetOperation")
        asset = operation.create
        
        # Thử sử dụng loại BUSINESS_NAME (v15+), nếu không có tự lùi về TEXT
        try:
            asset.type_ = client.enums.AssetTypeEnum.BUSINESS_NAME
            asset.business_name_asset.business_name = business_name
        except:
            try:
                asset.type_ = client.enums.AssetTypeEnum.BUSINESS_NAME_ASSET
                asset.business_name_asset.business_name = business_name
            except:
                # Fallback cuối cùng cho các phiên bản cũ
                asset.type_ = client.enums.AssetTypeEnum.TEXT
                asset.text_asset.text = business_name

        response = asset_service.mutate_assets(customer_id=customer_id, operations=[operation])
        return response.results[0].resource_name

    @staticmethod
    def _create_image_asset(client, customer_id, image_base64, name, target_ratio=1.0):
        """
        Tạo Image Asset từ base64 Odoo 
        Tự động đệm (Padding) để đạt tỷ lệ mong muốn:
        - target_ratio = 1.0 -> Ảnh vuông (1:1)
        - target_ratio = 1.91 -> Ảnh ngang (1.91:1)
        """
        import base64
        image_data_raw = base64.b64decode(image_base64)
        
        # --- Tự động bù tỷ lệ (Padding) ---
        try:
            from PIL import Image
            from io import BytesIO
            img = Image.open(BytesIO(image_data_raw))
            width, height = img.size
            current_ratio = width / height
            
            # Nếu tỷ lệ sai lệch đáng kể (> 5%)
            if abs(current_ratio - target_ratio) > 0.05:
                # Tính toán kích thước mới
                if current_ratio < target_ratio:
                    # Ảnh quá cao -> Bù chiều rộng
                    new_width = int(height * target_ratio)
                    new_height = height
                else:
                    # Ảnh quá rộng -> Bù chiều cao
                    new_width = width
                    new_height = int(width / target_ratio)
                
                # Tạo nền
                if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                    new_img = Image.new('RGBA', (new_width, new_height), (255, 255, 255, 0))
                else:
                    new_img = Image.new('RGB', (new_width, new_height), (255, 255, 255))
                
                # Dán ảnh vào giữa
                paste_x = (new_width - width) // 2
                paste_y = (new_height - height) // 2
                new_img.paste(img, (paste_x, paste_y))
                
                buffer = BytesIO()
                img_format = img.format if img.format else 'PNG'
                if new_img.mode == 'RGBA' and img_format == 'JPEG':
                    img_format = 'PNG'
                new_img.save(buffer, format=img_format)
                image_data = buffer.getvalue()
                _logger.info("Đã tự động đệm ảnh '%s' về tỷ lệ %.2f (%dx%d)", name, target_ratio, new_width, new_height)
            else:
                image_data = image_data_raw
        except Exception as e:
            _logger.warning("Không thể tự động chỉnh sửa ảnh '%s': %s", name, str(e))
            image_data = image_data_raw
        # ----------------------------------------
        
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
    def remove_campaign(client, customer_id, campaign_id):
        """Xóa vĩnh viễn campaign trên Google Ads (REMOVED)"""
        try:
            campaign_service = client.get_service("CampaignService")
            campaign_operation = client.get_type("CampaignOperation")
            campaign_operation.remove = campaign_service.campaign_path(customer_id, str(campaign_id))
            response = campaign_service.mutate_campaigns(customer_id=str(customer_id), operations=[campaign_operation])
            return True, response.results[0].resource_name
        except Exception as e:
            _logger.error("Remove campaign %s failed: %s", campaign_id, str(e))
            return False, str(e)

    @staticmethod
    def remove_ad_group(client, customer_id, ad_group_id):
        """Xóa vĩnh viễn ad group trên Google Ads"""
        try:
            ad_group_service = client.get_service("AdGroupService")
            ad_group_operation = client.get_type("AdGroupOperation")
            ad_group_operation.remove = ad_group_service.ad_group_path(str(customer_id), str(ad_group_id))
            response = ad_group_service.mutate_ad_groups(customer_id=str(customer_id), operations=[ad_group_operation])
            return True, response.results[0].resource_name
        except Exception as e:
            _logger.error("Remove ad group %s failed: %s", ad_group_id, str(e))
            return False, str(e)

    @staticmethod
    def remove_ad(client, customer_id, ad_group_id, ad_id):
        """Xóa vĩnh viễn mẫu quảng cáo trên Google Ads"""
        try:
            # Normalize ad_id
            pure_ad_id = str(ad_id).split('~')[-1]
            ad_group_ad_service = client.get_service("AdGroupAdService")
            ad_group_ad_operation = client.get_type("AdGroupAdOperation")
            # Resource name cho remove: "customers/{customer_id}/adGroupAds/{ad_group_id}~{ad_id}"
            ad_group_ad_operation.remove = f"customers/{customer_id}/adGroupAds/{ad_group_id}~{pure_ad_id}"
            response = ad_group_ad_service.mutate_ad_group_ads(customer_id=str(customer_id), operations=[ad_group_ad_operation])
            return True, response.results[0].resource_name
        except Exception as e:
            _logger.error("Remove ad %s failed: %s", ad_id, str(e))
            return False, str(e)

    @staticmethod
    def create_ad_group(client, customer_id, campaign_id, vals):
        """Tạo Ad Group trong một Campaign"""
        try:
            ad_group_service = client.get_service("AdGroupService")
            ad_group_operation = client.get_type("AdGroupOperation")
            ad_group = ad_group_operation.create

            ad_group.name = vals.get('name')
            ad_group.campaign = client.get_service("CampaignService").campaign_path(customer_id, campaign_id)

            # Map Status
            status_raw = vals.get('status', 'ENABLED').upper()
            try:
                ad_group.status = getattr(client.enums.AdGroupStatusEnum, status_raw)
            except AttributeError:
                ad_group.status = client.enums.AdGroupStatusEnum.ENABLED

            # Map Type
            type_raw = vals.get('type')
            if type_raw:
                try:
                    ad_group.type_ = getattr(client.enums.AdGroupTypeEnum, type_raw.upper())
                except AttributeError:
                    _logger.warning("Loại nhóm '%s' không tồn tại trong Client Enums.", type_raw)

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
        """Tạo mẫu quảng cáo (RSA hoặc Demand Gen) trong một Ad Group"""
        try:
            ad_group_ad_service = client.get_service("AdGroupAdService")
            ad_group_service = client.get_service("AdGroupService")
            
            # ═══════════════════════════════════════════════════════════
            # STRATEGY: Dùng native protobuf (_pb) để tránh hoàn toàn
            # các quirks của proto-plus gây ra IMMUTABLE_FIELD.
            # Proto-plus wrapper tự động khởi tạo sub-messages khi truy
            # cập attribute, gây "dirty state" trên field 'ad' immutable.
            # ═══════════════════════════════════════════════════════════
            ad_group_ad_operation = client.get_type("AdGroupAdOperation")
            
            # Truy cập trực tiếp native protobuf messages
            pb_op = ad_group_ad_operation._pb
            pb_ad_group_ad = pb_op.create
            
            # Set ad_group + status
            pb_ad_group_ad.ad_group = ad_group_service.ad_group_path(
                str(customer_id), str(ad_group_id)
            )
            pb_ad_group_ad.status = client.enums.AdGroupAdStatusEnum.ENABLED.value
            
            # Set Final URL trên pb_ad_group_ad.ad
            final_url = vals.get('final_url')
            if final_url:
                if not final_url.startswith('http'):
                    final_url = 'https://' + final_url
                pb_ad_group_ad.ad.final_urls.append(str(final_url))
            
            ad_type = vals.get('type', 'RESPONSIVE_SEARCH_AD').upper()

            if ad_type in ['DISCOVERY_RESPONSIVE_AD', 'DEMAND_GEN_RESPONSIVE_AD']:
                # --- Discovery / Demand Gen Ad content ---
                channel_type = vals.get('channel_type', '').upper()
                
                # Chọn đúng field dựa trên channel_type
                if channel_type in ['DEMAND_GEN', 'DISCOVERY']:
                    # Thử dùng demand_gen_responsive_ad nếu có
                    try:
                        info = pb_ad_group_ad.ad.demand_gen_responsive_ad
                        _logger.info("Sử dụng field demand_gen_responsive_ad (native pb)")
                    except AttributeError:
                        info = pb_ad_group_ad.ad.discovery_responsive_ad
                        _logger.info("Fallback discovery_responsive_ad (native pb)")
                else:
                    info = pb_ad_group_ad.ad.discovery_responsive_ad
                    _logger.info("Dùng discovery_responsive_ad mặc định (native pb)")

                info.business_name = str(vals.get('business_name') or "Brand")
                
                headlines = list(dict.fromkeys(vals.get('headlines', [])))
                for text in headlines[:5]:
                    h = info.headlines.add()
                    h.text = text[:40]
                
                descriptions = list(dict.fromkeys(vals.get('descriptions', [])))
                for text in descriptions[:5]:
                    d = info.descriptions.add()
                    d.text = text[:160]

                if vals.get('marketing_image_asset'):
                    img = info.marketing_images.add()
                    img.asset = vals.get('marketing_image_asset')
                
                if vals.get('square_marketing_image_asset'):
                    img = info.square_marketing_images.add()
                    img.asset = vals.get('square_marketing_image_asset')
                
                if vals.get('logo_image_asset'):
                    img = info.logo_images.add()
                    img.asset = vals.get('logo_image_asset')
            elif ad_type == 'SHOPPING_PRODUCT_AD':
                # --- Shopping Product Ad ---
                # According to API, no fields can be set for this ad type. 
                # Accessing the message is enough to initialize it in protobuf.
                _ = pb_ad_group_ad.ad.shopping_product_ad
                _logger.info("Sử dụng field shopping_product_ad (native pb)")
            else:
                # --- Default: Responsive Search Ad (RSA) ---
                rsa = pb_ad_group_ad.ad.responsive_search_ad
                
                unique_headlines = list(dict.fromkeys(vals.get('headlines', [])))
                for text in unique_headlines:
                    h = rsa.headlines.add()
                    h.text = text[:30]
                
                unique_descriptions = list(dict.fromkeys(vals.get('descriptions', [])))
                for text in unique_descriptions:
                    d = rsa.descriptions.add()
                    d.text = text[:90]

            # Debug: Log payload JSON trước khi gửi
            from google.protobuf.json_format import MessageToJson
            payload_json = MessageToJson(pb_op, preserving_proto_field_name=True)
            _logger.info(
                "create_ad payload (customer=%s, ad_group=%s, type=%s):\n%s",
                customer_id, ad_group_id, ad_type, payload_json
            )

            response = ad_group_ad_service.mutate_ad_group_ads(
                customer_id=str(customer_id),
                operations=[ad_group_ad_operation],
            )
            full_resource_name = response.results[0].resource_name
            # Trả về chỉ ad_id (phần sau dấu ~)
            return True, full_resource_name.split('~')[-1]
        except Exception as e:
            _logger.error("Create ad failed: %s", str(e))
            return False, str(e)


    @staticmethod
    def update_ad(client, customer_id, ad_group_id, ad_id, vals):
        """Cập nhật nội dung Ad (Headlines, Descriptions, URLs)"""
        try:
            # Normalize ad_id
            pure_ad_id = str(ad_id).split('~')[-1]
            
            # --- LƯU Ý: AdGroupAd.ad là immutable trong update của AdGroupAdService. ---
            # Ta phải sử dụng AdService để cập nhật tài nguyên Ad trực tiếp.
            ad_service = client.get_service("AdService")
            ad_operation = client.get_type("AdOperation")
            
            ad = ad_operation.update
            ad.resource_name = f"customers/{customer_id}/ads/{pure_ad_id}"
            
            mask_paths = []
            final_url = vals.get('final_url')
            if final_url:
                if not final_url.startswith('http'): final_url = 'https://' + final_url
                ad.final_urls.append(str(final_url))
                mask_paths.append("final_urls")
            
            # Determine ad content type
            ad_type = vals.get('type', 'RESPONSIVE_SEARCH_AD').upper()

            if ad_type in ['DISCOVERY_RESPONSIVE_AD', 'DEMAND_GEN_RESPONSIVE_AD']:
                channel_type = vals.get('channel_type', '').upper()
                if channel_type in ['DEMAND_GEN', 'DISCOVERY'] and hasattr(ad, 'demand_gen_responsive_ad'):
                    info = ad.demand_gen_responsive_ad
                    base_mask = "demand_gen_responsive_ad"
                else:
                    info = ad.discovery_responsive_ad
                    base_mask = "discovery_responsive_ad"

                if 'business_name' in vals:
                    info.business_name = str(vals.get('business_name'))
                    mask_paths.append(f"{base_mask}.business_name")

                if 'headlines' in vals:
                    unique_headlines = list(dict.fromkeys(vals.get('headlines', [])))
                    for text in unique_headlines[:5]:
                        h = client.get_type("AdTextAsset")
                        h.text = text[:40]
                        info.headlines.append(h)
                    mask_paths.append(f"{base_mask}.headlines")

                if 'descriptions' in vals:
                    unique_descriptions = list(dict.fromkeys(vals.get('descriptions', [])))
                    for text in unique_descriptions[:5]:
                        d = client.get_type("AdTextAsset")
                        d.text = text[:160]
                        info.descriptions.append(d)
                    mask_paths.append(f"{base_mask}.descriptions")

                if 'marketing_image_asset' in vals:
                    img = client.get_type("AdImageAsset")
                    img.asset = vals.get('marketing_image_asset')
                    info.marketing_images.append(img)
                    mask_paths.append(f"{base_mask}.marketing_images")

            else:
                # RSA content
                rsa = ad.responsive_search_ad
                
                # Headlines
                if 'headlines' in vals:
                    unique_headlines = list(dict.fromkeys(vals.get('headlines', [])))
                    for text in unique_headlines:
                        headline = client.get_type("AdTextAsset")
                        headline.text = text[:30]
                        rsa.headlines.append(headline)
                    mask_paths.append("responsive_search_ad.headlines")
                
                # Descriptions
                if 'descriptions' in vals:
                    unique_descriptions = list(dict.fromkeys(vals.get('descriptions', [])))
                    for text in unique_descriptions:
                        description = client.get_type("AdTextAsset")
                        description.text = text[:90]
                        rsa.descriptions.append(description)
                    mask_paths.append("responsive_search_ad.descriptions")

            # Field mask manually
            from google.protobuf.field_mask_pb2 import FieldMask
            ad_operation.update_mask.CopyFrom(FieldMask(paths=mask_paths))

            response = ad_service.mutate_ads(
                customer_id=str(customer_id),
                operations=[ad_operation],
            )
            return True, response.results[0].resource_name
        except Exception as e:
            _logger.error("Update ad content failed: %s", str(e))
            return False, str(e)

    @staticmethod
    def update_campaign_budget(client, customer_id, campaign_resource_name, new_budget_micros):
        """Cập nhật budget cho campaign"""
        try:
            ga_service = client.get_service("GoogleAdsService")
            
            # 1. Get the budget resource name from the campaign
            campaign_id = campaign_resource_name.split("/")[-1]
            query = f"SELECT campaign.campaign_budget FROM campaign WHERE campaign.id = {campaign_id}"
            
            response = ga_service.search(customer_id=customer_id, query=query)
            budget_resource_name = None
            for row in response:
                budget_resource_name = row.campaign.campaign_budget
                break
                
            if not budget_resource_name:
                return False, "Không tìm thấy ngân sách liên kết với chiến dịch này"
                
            # 2. Update the budget amount
            budget_service = client.get_service("CampaignBudgetService")
            budget_operation = client.get_type("CampaignBudgetOperation")
            
            budget = budget_operation.update
            budget.resource_name = budget_resource_name
            budget.amount_micros = int(new_budget_micros)
            
            # Field mask
            from google.protobuf.field_mask_pb2 import FieldMask
            mask_paths = ['amount_micros']
            budget_operation.update_mask.CopyFrom(FieldMask(paths=mask_paths))
            
            # Send mutate request
            budget_response = budget_service.mutate_campaign_budgets(
                customer_id=customer_id, operations=[budget_operation]
            )
            
            _logger.info("Campaign budget %s updated to %s micros.", budget_resource_name, new_budget_micros)
            return True, budget_response.results[0].resource_name
            
        except Exception as e:
            _logger.error("Update campaign budget failed: %s", str(e))
            return False, str(e)
