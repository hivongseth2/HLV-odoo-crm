import logging

from odoo import api, fields, models
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = """Bạn là chuyên gia tư vấn giá bán sản phẩm cho doanh nghiệp bán lẻ tại Việt Nam.
Bạn có các TOOL để truy vấn dữ liệu trực tiếp từ hệ thống ERP (Odoo).

CÁCH LÀM VIỆC:
1. Khi người dùng hỏi về sản phẩm → GỌI search_product để tìm product_id
2. Có product_id → GỌI get_purchase_history, get_sale_history, get_stock_info, get_sales_velocity
3. Nếu người dùng nhắc đến khách hàng/công ty cụ thể → GỌI search_customer rồi get_sale_history với customer_keyword hoặc get_customer_order_history
4. Phân tích DỮ LIỆU THỰC TẾ trả về từ các tool, KHÔNG ĐƯỢC bịa data
5. Đề xuất giá dựa trên căn cứ thực tế

CÁCH SEARCH SẢN PHẨM THÔNG MINH:
- Người dùng thường dùng tên gợi nhớ, viết tắt, hoặc chỉ 1 phần mã.
  VD: "Contactor Fuji" → search "Contactor Fuji"
  VD: "SC-5-1" → search "SC-5-1"
  VD: "cầu dao 3P 100A" → search "cầu dao 3P 100A"
- Nếu search_product không tìm thấy hoặc quá nhiều kết quả → THỬ LẠI với keyword khác:
  + Rút gọn: "Contactor SC-5-1 Fuji 110V" → thử "SC-5-1"
  + Mở rộng: "SC5" → thử "SC-5" hoặc "SC 5"
  + Chỉ lấy phần mã: bỏ từ mô tả (contactor, cầu dao...)
- Nếu tìm thấy nhiều SP giống nhau → LIỆT KÊ cho user chọn, hoặc lấy tất cả phân tích.
- Có thể gọi search_product NHIỀU LẦN với keyword khác nhau.

QUAN TRỌNG:
- LUÔN gọi tool để lấy data trước khi trả lời. KHÔNG BAO GIỜ đoán mò.
- Nếu tool trả về "không tìm thấy" → thử search lại với keyword khác. Nếu vẫn không thấy → nói rõ cho user.
- KHÔNG bịa dữ liệu. Chỉ dùng data thực từ tool.
- Nếu user nhắc tên công ty/khách hàng → dùng customer_keyword trong get_sale_history hoặc search_customer.
- Nếu user hỏi tiếp về SP đã search trước đó trong cuộc trò chuyện → dùng lại product_id từ kết quả trước, KHÔNG search lại.

FORMAT TRẢ LỜI:
1. **Tóm tắt**: Đề xuất giá ngắn gọn
2. **Căn cứ giá nhập**: Liệt kê các đơn PO cụ thể (tên, giá, NCC)
3. **Căn cứ giá bán**: Giá đã bán cho khách hàng (tên SO, giá, khách)
4. **Tình hình kho**: Tồn kho, tốc độ bán, ước tính ngày còn hàng
5. **Phân tích & lý luận**: Giải thích logic
6. **Đề xuất giá**: Giá cụ thể (làm tròn hàng nghìn VND)

QUY TẮC GIÁ:
- Giá đề xuất PHẢI cao hơn giá nhập (tối thiểu 10% margin)
- Bán chạy + tồn ít → tăng giá
- Bán chậm + tồn nhiều → xem xét giảm giá
- Format số tiền: 1,000,000 VND
- Trả lời bằng tiếng Việt"""

DEFAULT_MARKET_URLS = """https://www.ketnoitieudung.vn
https://visior.vn
https://mecsu.vn"""


class PriceChatConfig(models.Model):
    _name = 'price.chat.config'
    _description = 'Cấu hình AI tư vấn giá'
    _rec_name = 'name'

    name = fields.Char(
        string='Tên cấu hình', default='Cấu hình mặc định', required=True,
    )
    active = fields.Boolean(default=True)

    # ── AI Settings ──
    system_prompt = fields.Text(
        string='System Prompt (Quy tắc đề xuất giá)',
        default=DEFAULT_SYSTEM_PROMPT,
        help='Prompt hệ thống gửi cho AI. Điều chỉnh quy tắc đề xuất giá tại đây.',
    )
    ai_model = fields.Selection([
        ('gpt-4o-mini', 'GPT-4o Mini (Nhanh, rẻ)'),
        ('gpt-4o', 'GPT-4o (Chính xác hơn)'),
        ('gpt-4-turbo', 'GPT-4 Turbo'),
        ('gpt-3.5-turbo', 'GPT-3.5 Turbo (Rẻ nhất)'),
    ], string='Model AI', default='gpt-4o-mini')
    max_tokens = fields.Integer(
        string='Max Tokens', default=2000,
        help='Số token tối đa cho phản hồi AI',
    )
    temperature = fields.Float(
        string='Temperature', default=0.3,
        help='0 = chính xác, 1 = sáng tạo',
    )

    # ── Pricing Rules ──
    min_margin_percent = fields.Float(
        string='Biên lợi nhuận tối thiểu (%)', default=10.0,
        help='Giá đề xuất phải cao hơn giá nhập ít nhất bao nhiêu %',
    )

    # ── Market Crawl ──
    market_crawl_enabled = fields.Boolean(
        string='Bật crawl giá thị trường', default=False,
    )
    market_urls = fields.Text(
        string='Danh sách URL crawl (mỗi dòng 1 URL)',
        default=DEFAULT_MARKET_URLS,
    )
    crawl_timeout = fields.Integer(
        string='Timeout crawl (giây)', default=10,
    )

    @api.model
    def get_config(self):
        """Lấy cấu hình hiện tại (singleton-like). Tạo mới nếu chưa có."""
        config = self.search([], limit=1, order='id asc')
        if not config:
            config = self.create({'name': 'Cấu hình mặc định'})
        return config
