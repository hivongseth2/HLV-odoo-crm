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
    ADSROID_ENDPOINT_ANALYZE = "https://rckoycauuwzdryvkjpac.supabase.co/functions/v1/adsroid"

    @staticmethod
    def analyze_campaign(api_key, organisation_id, project_id, campaign_data, product_data, is_demo=False, user_query=None):
        """
        Gửi dữ liệu chiến dịch và sản phẩm lên Adsroid để nhận AI Insights.
        Xử lý cả chế độ phân tích tự động và chế độ Chat nếu có user_query.
        """
        if is_demo:
            _logger.info("[DEMO MODE] Trả về dữ liệu mô phỏng AI (Mock) cho chiến dịch: %s", campaign_data.get('name'))
            return True, AdsroidApiService._mock_ai_response(campaign_data, product_data, user_query)

        if not api_key or not organisation_id or not project_id:
            return False, _("Thiếu cấu hình Adsroid (API Key, Org ID hoặc Project ID).")

        # Chuẩn bị nội dung 'message' cho AI phân tích
        data_str = json.dumps({
            "campaign": campaign_data,
            "products": product_data
        }, indent=2, ensure_ascii=False)
        
        if user_query:
            # Chế độ CHAT: AI trả lời dựa trên câu hỏi người dùng và ngữ cảnh data
            message = (
                "Bạn là Adsroid AI Assistant. Hãy trả lời câu hỏi của người dùng dựa trên dữ liệu Google Ads sau đây. "
                "Bạn có quyền đề xuất thay đổi cụ thể nếu cần.\n\n"
                "YÊU CẦU: Bạn PHẢI trả về định dạng JSON chứa 'insight' (câu trả lời) và tùy chọn 'new_budget' hoặc 'new_status' nếu muốn thực hiện thay đổi.\n"
                "{\n"
                "  \"insight\": \"Câu trả lời của bạn...\",\n"
                "  \"suggested_action\": \"ADJUST_BUDGET\" | \"PAUSE\" | \"ENABLE\" | \"MAINTAIN\",\n"
                "  \"new_budget\": 1000000, // Chỉ điền nếu muốn đổi ngân sách (VND)\n"
                "  \"score\": 85\n"
                "}\n\n"
                f"Dữ liệu ngữ cảnh: {data_str}\n"
                f"Câu hỏi của người dùng: {user_query}"
            )
        else:
            # Chế độ PHÂN TÍCH (Analyze): AI tự quét và đưa ra đề xuất
            message = (
                "Hãy đóng vai là một chuyên gia tối ưu hóa quảng cáo Google Ads. "
                "Hãy phân tích dữ liệu chiến dịch và tồn kho sau đây để đưa ra quyết định tối ưu nhất.\n\n"
                "YÊU CẦU QUAN TRỌNG: Bạn chỉ được phản hồi bằng định dạng JSON theo đúng cấu trúc sau:\n"
                "{\n"
                "  \"score\": 85, // Điểm hiệu suất 0-100\n"
                "  \"suggested_action\": \"PAUSE\" | \"ENABLE\" | \"ADJUST_BUDGET\" | \"MAINTAIN\",\n"
                "  \"new_budget\": 1200000, // QUAN TRỌNG: Nếu đề xuất tăng/giảm, hãy ghi rõ số tiền ngân sách mới (VND) bạn muốn đặt.\n"
                "  \"insight\": \"Nội dung nhận định chi tiết, giải thích lý do tại sao bạn chọn ngân sách đó bằng tiếng Việt...\"\n"
                "}\n\n"
                f"Dữ liệu: {data_str}"
            )

        payload = {
            "organisation_id": organisation_id,
            "project_id": project_id,
            "message": message
        }

        headers = {
            "Authorization": f"bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        _logger.info("Gửi yêu cầu Adsroid cho chiến dịch: %s (User Query: %s)", campaign_data.get('name'), user_query or 'None')

        try:
            response = requests.post(
                AdsroidApiService.ADSROID_ENDPOINT_ANALYZE,
                headers=headers,
                data=json.dumps(payload),
                timeout=25 # Tăng timeout cho chat
            )

            if response.status_code != 200:
                _logger.warning("Adsroid API trả về lỗi: %s - %s", response.status_code, response.text)
                return False, _("Lỗi phản hồi từ server Adsroid (Code: %s): %s") % (response.status_code, response.text)

            res_data = response.json()
            content = ""
            if isinstance(res_data, dict):
                content = res_data.get('response') or res_data.get('message') or str(res_data)
            else:
                content = str(res_data)

            try:
                import re
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group())
                    # Đồng bộ hóa suggested_action nếu AI dùng từ khác
                    if 'new_budget' in parsed and not parsed.get('suggested_action'):
                        parsed['suggested_action'] = 'ADJUST_BUDGET'
                    return True, parsed
                return True, {"insight": content, "suggested_action": "MAINTAIN", "score": 0}
            except:
                return True, {"insight": content, "suggested_action": "MAINTAIN", "score": 0}

        except requests.exceptions.Timeout:
            return False, _("Kết nối tới Adsroid bị quá hạn (Timeout).")
        except requests.exceptions.RequestException as e:
            _logger.error("Lỗi khi kết nối mạng tới Adsroid API: %s", str(e))
            return False, _("Không thể kết nối với mạng API Adsroid: %s") % str(e)
        except Exception as e:
            return False, str(e)

    @staticmethod
    def _mock_ai_response(campaign_data, product_data, user_query=None):
        """Giả lập phản hồi từ AI Agent khi chưa có Endpoint chuẩn hoặc ở chế độ Demo"""
        metrics = campaign_data.get('metrics', {})
        cost = metrics.get('cost', 0)
        conv = metrics.get('conversions', 0)
        roas = (conv * 500000) / cost if cost > 0 else 0
        current_budget = campaign_data.get('metrics', {}).get('budget', 50000)

        # Kiểm tra tồn kho sản phẩm
        low_stock_products = [p for p in product_data if p.get('qty_available', 0) <= 20]
        
        if user_query:
            # Giả lập trả lời chat
            return {
                "score": 80,
                "suggested_action": "MAINTAIN",
                "insight": f"Đây là câu trả lời giả lập cho câu hỏi: '{user_query}'. Dữ liệu cho thấy ROAS của bạn đang ở mức {roas:.1f}x."
            }

        if low_stock_products:
            action = "PAUSE"
            new_budget = current_budget
            message = f"Adsroid đề xuất: TẠM DỪNG. Phát hiện {len(low_stock_products)} sản phẩm đang sắp hết hàng, tránh lãng phí ngân sách."
        elif roas < 1.5 and cost > 200000:
            action = "ADJUST_BUDGET"
            new_budget = round(current_budget * 0.7, -3) # Giảm 30%
            message = f"Adsroid đề xuất: GIẢM NGÂN SÁCH về {new_budget:,}đ. Hiệu quả ROAS thấp, cần tối ưu lại từ khóa."
        elif roas >= 4.0:
            action = "ADJUST_BUDGET"
            new_budget = round(current_budget * 1.5, -3) # Tăng 50%
            message = f"Adsroid đề xuất: TĂNG NGÂN SÁCH lên {new_budget:,}đ. Hiệu quả đang rất tốt, hãy mở rộng quy mô."
        else:
            action = "MAINTAIN"
            new_budget = current_budget
            message = "Adsroid đề xuất: GIỮ NGUYÊN. Các chỉ số đang ở mức ổn định."

        return {
            "score": round(roas * 10, 2),
            "suggested_action": action,
            "new_budget": new_budget,
            "insight": message
        }
