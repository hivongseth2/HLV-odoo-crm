"""
Google Ads Conversion Service
─────────────────────────────
Xử lý đẩy chuyển đổi Offline (GCLID) từ Odoo lên Google Ads.
Cho phép bỏ qua GTM để ghi nhận doanh thu chính xác 100%.
"""
import logging
from odoo import _

_logger = logging.getLogger(__name__)

class GoogleAdsConversionService:
    
    @staticmethod
    def upload_click_conversion(client, customer_id, conversion_data):
        """Đẩy một lượt chuyển đổi lên Google Ads
        
        conversion_data = {
            'gclid': str,
            'conversion_action_id': str,
            'conversion_date_time': str (Format: yyyy-mm-dd hh:mm:ss+tz),
            'conversion_value': float,
            'currency_code': str (VD: "VND")
        }
        """
        try:
            conversion_upload_service = client.get_service("ConversionUploadService")
            click_conversion = client.get_type("ClickConversion")
            
            conversion_action_service = client.get_service("ConversionActionService")
            
            click_conversion.conversion_action = conversion_action_service.conversion_action_path(
                customer_id, conversion_data['conversion_action_id']
            )
            click_conversion.gclid = conversion_data['gclid']
            click_conversion.conversion_value = conversion_data['conversion_value']
            click_conversion.currency_code = conversion_data['currency_code']
            click_conversion.conversion_date_time = conversion_data['conversion_date_time']

            response = conversion_upload_service.upload_click_conversions(
                customer_id=customer_id,
                conversions=[click_conversion],
                partial_failure=True,
            )
            
            if hasattr(response, 'partial_failure_error') and response.partial_failure_error.code != 0:
                return False, response.partial_failure_error.message
                
            return True, response.results[0].conversion_date_time
            
        except Exception as e:
            _logger.error("Upload conversion failed: %s", str(e))
            return False, str(e)
