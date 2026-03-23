"""
Adsroid API Integration Service
───────────────────────────────
Tích hợp API của Adsroid.com để phân tích dữ liệu Google Ads và sản phẩm,
trả về các nhận định (Insights) và đề xuất hành động (Actions).
"""
import requests
import json
import logging
from odoo.exceptions import UserError
from odoo import _

_logger = logging.getLogger(__name__)

class AdsroidApiService:
    """Service gọi API Adsroid để phân tích chiến dịch"""
    
    # TODO: Thay đổi Endpoint khi có tài liệu API chính thức từ Adsroid
    ADSROID_ENDPOINT_ANALYZE = "https://api.adsroid.com/v1/analyze"

    @staticmethod
    def analyze_campaign(api_key, campaign_data, product_data, is_demo=False):
        """
        Gửi dữ liệu chiến dịch và sản phẩm lên Adsroid để nhận AI Insights.
        
        :param api_key: str - API Key lấy từ cấu hình
        :param campaign_data: dict - Thông tin chiến dịch và metrics hiện tại
        :param product_data: list of dict - Dữ liệu tồn kho, biên lợi nhuận của sản phẩm
        :param is_demo: bool - Trạng thái Demo Mode
        :return: (bool, str/dict) - (True, kết_quả_json) hoặc (False, lỗi_message)
        """
        if is_demo:
            _logger.info("[DEMO MODE] Trả về dữ liệu mô phỏng AI (Mock) cho chiến dịch: %s", campaign_data.get('name'))
            return True, AdsroidApiService._mock_ai_response(campaign_data, product_data)

        if not api_key:
            return False, _("Thiếu cấu hình Adsroid API Key.")

        payload = {
            "campaign": campaign_data,
            "products": product_data
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        _logger.info("Gửi yêu cầu phân tích tới Adsroid cho chiến dịch: %s", campaign_data.get('name'))

        try:
            # Gửi HTTP Request tới Adsroid (Mock/Placeholder nếu endpoint chưa public)
            # Timeout 15s để tránh block Odoo
            response = requests.post(
                AdsroidApiService.ADSROID_ENDPOINT_ANALYZE,
                headers=headers,
                data=json.dumps(payload),
                timeout=15
            )

            # Trả về lỗi nếu gọi API thực tế thất bại
            if response.status_code != 200:
                _logger.warning("Adsroid API trả về lỗi: %s - %s", response.status_code, response.text)
                return False, _("Lỗi phản hồi từ server Adsroid (Code: %s): %s") % (response.status_code, response.text)

            # Xử lý thành công
            return True, response.json()

        except requests.exceptions.Timeout:
            return False, _("Kết nối tới Adsroid bị quá hạn (Timeout).")
        except requests.exceptions.RequestException as e:
            _logger.error("Lỗi khi kết nối mạng tới Adsroid API: %s", str(e))
            return False, _("Không thể kết nối với mạng API Adsroid: %s") % str(e)
        except Exception as e:
            return False, str(e)

    @staticmethod
    def _mock_ai_response(campaign_data, product_data):
        """Giả lập phản hồi từ AI Agent khi chưa có Endpoint chuẩn"""
        metrics = campaign_data.get('metrics', {})
        cost = metrics.get('cost', 0)
        conv = metrics.get('conversions', 0)
        roas = (conv * 500000) / cost if cost > 0 else 0

        # Kiểm tra tồn kho sản phẩm
        low_stock_products = [p for p in product_data if p.get('qty_available', 0) <= 20]
        
        if low_stock_products:
            action = "PAUSE"
            message = f"AI Đề xuất: TẠM DỪNG. Phát hiện {len(low_stock_products)} sản phẩm trong chiến dịch đang sắp hết hàng."
        elif roas < 2.0 and cost > 100000:
            action = "DECREASE_BUDGET"
            message = "AI Đề xuất: GIẢM NGÂN SÁCH. ROAS hiện tại < 2.0, quảng cáo đang tiêu tốn nhiều chi phí mà không đem lại chuyển đổi tốt."
        elif roas >= 3.0:
            action = "INCREASE_BUDGET"
            message = "AI Đề xuất: TĂNG NGÂN SÁCH. ROAS rất tốt (>= 3.0), tồn kho đảm bảo."
        else:
            action = "MAINTAIN"
            message = "AI Đề xuất: GIỮ NGUYÊN. Chiến dịch đang hoạt động ổn định ở mức chấp nhận được."

        return {
            "score": round(roas * 10, 2),
            "suggested_action": action,
            "insight": message,
            "raw_data_received": {
                "campaign_id": campaign_data.get('id'),
                "products_count": len(product_data)
            }
        }
