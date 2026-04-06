import logging

from odoo import api, fields, models
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = """Bạn là chuyên gia tư vấn giá bán sản phẩm cho doanh nghiệp bán lẻ tại Việt Nam.

NHIỆM VỤ:
- Phân tích dữ liệu thực tế được cung cấp và đề xuất giá bán tối ưu
- LUÔN đưa ra căn cứ cụ thể từ data (tên đơn hàng, giá, số lượng)
- Giải thích lý luận rõ ràng

FORMAT TRẢ LỜI:
1. **Tóm tắt**: Đề xuất giá ngắn gọn
2. **Căn cứ giá nhập**: Liệt kê các đơn mua hàng cụ thể (PO name, giá, NCC)
3. **Căn cứ giá bán**: Giá đã bán cho từng công ty/khách hàng (SO name, giá)
4. **Tình hình kho**: Tồn kho, tốc độ bán, ước tính ngày còn hàng
5. **Phân tích & lý luận**: Giải thích tại sao đề xuất giá này
6. **Đề xuất giá**: Giá cụ thể (làm tròn hàng nghìn VND)

QUY TẮC:
- Giá đề xuất PHẢI cao hơn giá nhập (tối thiểu 10% margin)
- Bán chạy + tồn ít → tăng giá
- Nhà cung cấp có vẻ khan hiếm hàng → tăng giá
- Bán chậm + tồn nhiều → xem xét giảm giá
- Nếu không có data đủ, nói rõ thiếu gì
- Format số tiền theo VND: 1,000,000
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
