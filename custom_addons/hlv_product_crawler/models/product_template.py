from odoo import models, fields, api, _
from odoo.exceptions import UserError
from .crawler_parsers import CrawlerUtils

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    ketnoitieudung_url = fields.Char(string="Link Ketnoitieudung", help="Link crawling thông số kỹ thuật từ ketnoitieudung.vn")
    visior_url = fields.Char(string="Link Visior", help="Link crawling thông số kỹ thuật từ visior.vn")
    thbvietnam_url = fields.Char(string="Link THB Vietnam", help="Link crawling thông số kỹ thuật từ thbvietnam.com")
    mecsu_url = fields.Char(string="Link Mecsu", help="Link crawling thông số kỹ thuật từ mecsu.vn")
    milwaukee_url = fields.Char(string="Link Milwaukee", help="Link crawling thông số kỹ thuật từ milwaukeetool.com.vn")
    bosch_url = fields.Char(string="Link Bosch", help="Link crawling thông số kỹ thuật từ vn.bosch-pt.com")
    
    crawled_specs_raw = fields.Html(string="Dữ liệu thô (Crawl)", help="Dữ liệu gốc lấy từ website")
    crawled_specs_analyzed = fields.Html(string="Dữ liệu đã phân tích (AI)", help="Dữ liệu đã được AI tổng hợp và làm sạch")
    
    # Backward compatibility: related to crawled_specs_raw to prevent View Errors during upgrade
    crawled_specs = fields.Html(related='crawled_specs_raw', string="Crawled Specifications (Legacy)", readonly=True)

    # AI QC Fields
    ai_verify_score = fields.Integer(string="Điểm chất lượng (AI)", readonly=True, help="Điểm chất lượng (0-100) từ Mr. GPT")
    ai_verify_analysis = fields.Html(string="Phân tích của AI", readonly=True)
    ai_last_verify_date = fields.Datetime(string="Ngày kiểm tra", readonly=True)
    
    # Catalog/Document Links
    catalog_links = fields.Text(string="Tài liệu kỹ thuật", help="Catalog PDF và tài liệu kỹ thuật từ nguồn crawl")

    def _call_gpt_verification(self):
        """
        Core GPT verification logic. Returns (score, analysis) tuple.
        Returns (None, None) if API key not configured or on error.
        """
        self.ensure_one()
        api_key = self.env['ir.config_parameter'].sudo().get_param('product_crawler.openai_api_key')
        if not api_key:
            return None, None
            
        model = self.env['ir.config_parameter'].sudo().get_param('product_crawler.openai_model') or 'gpt-4o-mini'
        
        # Prepare content
        sku = self.default_code or "N/A"
        name = self.name or "N/A"
        specs = self.crawled_specs_raw or "Chưa có dữ liệu crawl."
        
        prompt = f"""Bạn là Mr. GPT, chuyên gia kiểm soát chất lượng (QC) nghiêm ngặt về Dụng cụ Công nghiệp.
Phân tích dữ liệu đã crawl cho sản phẩm SKU: {sku}, Tên: {name}.
Dữ liệu:
{specs}

Nhiệm vụ: Xác minh xem dữ liệu này có khớp kỹ thuật với sản phẩm không.
Luật:
1. Bỏ qua các lỗi định dạng nhỏ.
2. Tập trung vào Thông số kỹ thuật (Điện áp, Vòng tua, Trọng lượng, Mã model).
3. Nếu Thông số bị thiếu hoặc rõ ràng thuộc về sản phẩm khác (ví dụ: M12 vs M18), hãy TRỪ điểm nặng.
4. Nếu Thông số bị trùng lặp nhưng đúng, chỉ trừ điểm nhẹ.
5. Trả về DUY NHẤT JSON theo định dạng: {{"score": 0-100, "reason": "Chuỗi phân tích định dạng HTML (tiếng Việt)"}}."""

        import requests
        import json
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        data = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a helpful QC assistant returning JSON. Reply in Vietnamese."},
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"}
        }
        
        try:
            response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=data, timeout=30)
            response.raise_for_status()
            result = response.json()
            
            content = result['choices'][0]['message']['content']
            parsed = json.loads(content)
            
            score = parsed.get('score', 0)
            analysis = parsed.get('reason', 'No analysis returned.')
            
            return score, analysis
            
        except Exception as e:
            import logging
            _logger = logging.getLogger(__name__)
            _logger.error(f"GPT Verification failed: {str(e)}")
            return None, None

    def _verify_url_matches_product(self, url):
        """
        Verify if URL matches the product before crawling.
        Returns (is_valid, reason) tuple.
        is_valid is True if URL likely correct, False if wrong product, None if verification skipped.
        """
        self.ensure_one()
        
        # Skip if no API key configured
        api_key = self.env['ir.config_parameter'].sudo().get_param('product_crawler.openai_api_key')
        if not api_key:
            return None, "API key not configured"
            
        model = self.env['ir.config_parameter'].sudo().get_param('product_crawler.openai_model') or 'gpt-4o-mini'
        
        sku = self.default_code or "N/A"
        name = self.name or "N/A"
        
        # Detect Mecsu URLs for specialized fuzzy matching
        is_mecsu = 'mecsu.vn' in url.lower()
        
        if is_mecsu:
            # Mecsu-specific fuzzy matching prompt
            prompt = f"""Bạn là Mr. GPT, chuyên gia khớp sản phẩm cho bulong ốc vít và phần cứng công nghiệp.

Sản phẩm trong hệ thống:
- Tên: {name}
- SKU: {sku}

Link tìm thấy: {url}

Nhiệm vụ: Xác minh xem Link này có đúng là của sản phẩm trên không.

QUAN TRỌNG - Quy tắc khớp linh hoạt cho Mecsu:
1. Từ đồng nghĩa vật liệu được chấp nhận:
   - SS304 = Inox 304 = Stainless Steel 304 = INOX A2
   - SS316 = Inox 316 = A4
   - Thép = Steel
2. Định dạng số tiêu chuẩn linh hoạt:
   - DIN912 = 912 = DIN 912
   - ISO = DIN (thường thay thế cho nhau cùng thông số)
3. Thứ tự từ không quan trọng:
   - "Bu lông lục giác M5x15" khớp "Lục giác chìm đầu M5x15"
   - Tập trung vào thông số kỹ thuật, không phải thứ tự từ
4. CÁC ĐỊNH DANH CHÍNH BẮT BUỘC KHỚP:
   - Kích thước (M5x15, M6x20, v.v.) - PHẢI khớp chính xác
   - Số tiêu chuẩn (912, 933, 7991, v.v.) - PHẢI khớp
   - Loại vật liệu tương thích (inox/thép)
5. Bỏ qua các từ mô tả không quan trọng:
   - "Chìm đầu", "Đầu trụ", "Lục giác" là mô tả
   - Các từ này thay đổi tùy cách gọi, không quan trọng

Ngưỡng độ tin cậy:
- 90-100%: Rất tự tin khớp
- 70-89%: Khả năng cao khớp (dùng được)
- <70%: Không khớp

Trả về JSON: {{"is_correct": true/false, "confidence": 0-100, "reason": "giải thích ngắn gọn tiếng Việt"}}

Ví dụ:
✅ "Bu lông SS304 DIN912 M5x15" + URL "luc-giac-chim-dau-tru-inox-304-din912-m5x15" → TRUE (size + tiêu chuẩn khớp, vật liệu tương đương)
✅ "Ốc lục giác 912 M6x20 Inox" + URL "din912-m6x20-inox-304" → TRUE (specs chính khớp)
❌ "Bu lông M5x15" + URL "m6x20" → FALSE (sai size)
❌ "DIN912 M5" + URL "din933-m5" → FALSE (sai tiêu chuẩn)
"""
        else:
            # Standard strict matching for other sites
            prompt = f"""Bạn là Mr. GPT, chuyên gia xác minh link sản phẩm.

Thông tin sản phẩm:
- SKU: {sku}
- Tên sản phẩm: {name}

Link tìm thấy: {url}

Nhiệm vụ: Phân tích xem Link này có chứa thông số đúng cho sản phẩm không.
Kiểm tra:
1. Domain khớp (ví dụ: Sản phẩm Milwaukee phải ở milwaukeetool.com, không phải bosch-pt.com)
2. Đường dẫn/slug chứa SKU, thương hiệu, hoặc định danh model
3. Sự nhất quán về loại sản phẩm

Trả về DUY NHẤT JSON: {{"is_correct": true/false, "confidence": 0-100, "reason": "giải thích ngắn gọn lý do tại sao khớp hoặc không khớp bằng tiếng Việt"}}

Ví dụ:
- Milwaukee M18 FPD3 + bosch-pt.com URL → is_correct: false
- Milwaukee M18 FPD3 + milwaukeetool.com/m18-planer → is_correct: true
"""

        import requests
        import json
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        data = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a helpful URL verification assistant returning JSON. Reply in Vietnamese."},
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"}
        }
        
        try:
            response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=data, timeout=30)
            response.raise_for_status()
            result = response.json()
            
            content = result['choices'][0]['message']['content']
            parsed = json.loads(content)
            
            is_correct = parsed.get('is_correct', False)
            reason = parsed.get('reason', 'No reason provided')
            
            return is_correct, reason
            
        except Exception as e:
            import logging
            _logger = logging.getLogger(__name__)
            _logger.error(f"URL Verification failed: {str(e)}")
            return None, f"Verification error: {str(e)}"

    def _auto_verify_after_crawl(self):
        """
        Automatically verify crawled specs with GPT after crawling.
        Modifies crawled_specs based on verification score.
        """
        self.ensure_one()
        
        # Skip if no specs were crawled
        if not self.crawled_specs_raw:
            return
        
        score, analysis = self._call_gpt_verification()
        
        # Skip if GPT verification failed or not configured
        if score is None:
            return
        
        # Store verification results
        self.ai_verify_score = score
        self.ai_verify_analysis = analysis
        self.ai_last_verify_date = fields.Datetime.now()
        
        # Add verification badge to specs based on score
        if score >= 80:
            badge = f"""
            <div style='background: #d4edda; border: 1px solid #c3e6cb; border-radius: 4px; padding: 10px; margin: 10px 0; color: #155724;'>
                ✅ <strong>Mr. GPT Đã duyệt ({score}/100)</strong> - Dữ liệu tốt!
            </div>"""
            self.crawled_specs_raw += badge
        elif score >= 50:
            badge = f"""
            <div style='background: #fff3cd; border: 1px solid #ffeaa7; border-radius: 4px; padding: 10px; margin: 10px 0; color: #856404;'>
                ⚠️ <strong>Cần kiểm tra lại ({score}/100)</strong> - Vui lòng check thủ công. {analysis[:100]}...
            </div>"""
            self.crawled_specs_raw += badge
        else:
            # Score < 50: Replace specs with error message
            self.crawled_specs_raw = f"""
            <div style='background: #f8d7da; border: 1px solid #f5c6cb; border-radius: 4px; padding: 15px; margin: 10px 0; color: #721c24;'>
                ❌ <strong>GPT Từ chối: Sai sản phẩm ({score}/100)</strong>
                <p>{analysis}</p>
                <p><em>Dữ liệu crawl được không khớp với sản phẩm này. Hãy kiểm tra Link hoặc SKU.</em></p>
            </div>"""

    def action_ai_verify(self):
        """Manual GPT verification action (for re-verification or initial check)"""
        self.ensure_one()
        
        api_key = self.env['ir.config_parameter'].sudo().get_param('product_crawler.openai_api_key')
        if not api_key:
            raise UserError(_("OpenAI API Key is not configured in Settings."))
        
        score, analysis = self._call_gpt_verification()
        
        if score is None:
            raise UserError(_("AI Verification Failed. Please check logs."))
        
        self.ai_verify_score = score
        self.ai_verify_analysis = analysis
        self.ai_last_verify_date = fields.Datetime.now()
        
        # Return notification
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Mr. GPT Hoàn thành'),
                'message': f"Điểm chất lượng: {self.ai_verify_score}/100",
                'sticky': False,
                'type': 'success' if self.ai_verify_score >= 80 else 'warning',
            }
        }

    def action_crawl_and_analyze(self):
        """Crawl data from all sources and then analyze/consolidate"""
        self.ensure_one()
        
        # 1. Crawl all data
        self.action_crawl_all()
        
        # 2. Analyze if API key exists
        api_key = self.env['ir.config_parameter'].sudo().get_param('product_crawler.openai_api_key')
        if api_key:
            self.action_analyze_specs()
        else:
             return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Hoàn thành lấy dữ liệu'),
                    'message': "Đã lấy dữ liệu thô. Vui lòng cấu hình API Key để tự động phân tích.",
                    'sticky': False,
                    'type': 'warning',
                }
            }

    def action_analyze_specs(self):
        """Analyze and consolidate raw specs using GPT"""
        self.ensure_one()
        
        api_key = self.env['ir.config_parameter'].sudo().get_param('product_crawler.openai_api_key')
        if not api_key:
            raise UserError(_("OpenAI API Key is not configured in Settings."))
        
        if not self.crawled_specs_raw:
            raise UserError(_("Chưa có dữ liệu thô. Vui lòng lấy dữ liệu trước."))
        
        model = self.env['ir.config_parameter'].sudo().get_param('product_crawler.openai_model') or 'gpt-4o-mini'
        
        sku = self.default_code or "N/A"
        name = self.name or "N/A"
        raw_data = self.crawled_specs_raw
        
        prompt = f"""Bạn là Mr. GPT, chuyên gia viết tài liệu kỹ thuật cho dụng cụ công nghiệp.

Sản phẩm: {name} (SKU: {sku})

Dữ liệu thô từ nhiều nguồn:
{raw_data}

Nhiệm vụ: Tổng hợp dữ liệu thô này thành MỘT tài liệu thông số kỹ thuật CHUYÊN NGHIỆP, SẠCH SẼ.

Luật:
1. Gộp các thông tin trùng lặp (giữ giá trị chính xác nhất).
2. Tổ chức thành các phần: Đánh giá chung, Thông số kỹ thuật, Đặc điểm nổi bật.
3. Loại bỏ tất cả metadata thừa (tiêu đề nguồn crawl, thông báo tìm kiếm, lỗi, badge kiểm tra).
4. Chỉ giữ lại thông số và tính năng thực tế của sản phẩm.
5. Định dạng HTML sạch đẹp với tiêu đề và bảng.
6. Nếu có dữ liệu mâu thuẫn, dùng biểu quyết số đông hoặc nguồn chi tiết nhất.
7. Trả về DUY NHẤT nội dung HTML đã tổng hợp, không kèm lời dẫn.

Định dạng đầu ra mong muốn:
<h2>Tổng quan sản phẩm</h2>
<p>Mô tả ngắn...</p>

<h2>Thông số kỹ thuật</h2>
<table>...</table>

<h2>Đặc điểm nổi bật</h2>
<ul>...</ul>
"""

        import requests
        import json
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        data = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a helpful technical writing assistant. Reply in Vietnamese."},
                {"role": "user", "content": prompt}
            ]
        }
        
        try:
            response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=data, timeout=60)
            response.raise_for_status()
            result = response.json()
            
            consolidated = result['choices'][0]['message']['content']
            
            # Save to analyzed field
            self.crawled_specs_analyzed = f"""
            <div style='background: #cfe2ff; border: 1px solid #9ec5fe; padding: 10px; margin: 10px 0; color: #052c65;'>
                🤖 <b>Đã phân tích bởi Mr. GPT</b> - Văn bản này được tổng hợp tự động từ dữ liệu thô.
            </div>
            {consolidated}
            """
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Mr. GPT Hoàn thành'),
                    'message': "Dữ liệu đã được phân tích và tổng hợp.",
                    'sticky': False,
                    'type': 'success',
                }
            }
            
        except Exception as e:
            raise UserError(_(f"Consolidation Failed: {str(e)}"))

    def action_crawl_ketnoitieudung(self):
        import logging
        _logger = logging.getLogger(__name__)
        
        self.ensure_one()
        _logger.info(f"[Ketnoitieudung] Starting crawl, current URL: {self.ketnoitieudung_url}")
        
        url = self.ketnoitieudung_url
        if not url and self.default_code:
            msg_searching = f"<div style='color: #6c757d; font-size: 0.9em;'>🔍 Đang tìm kiếm <b>{self.default_code}</b> trên Ketnoitieudung.vn...</div>"
            self.crawled_specs_raw = (self.crawled_specs_raw or "") + msg_searching
            
            _logger.info(f"[Ketnoitieudung] Searching for SKU: {self.default_code}, Name: {self.name}")
            # Pass both SKU and product name
            url, error = CrawlerUtils.search_ketnoitieudung(self.default_code, self.name)
            _logger.info(f"[Ketnoitieudung] Search result - URL: {url}, Error: {error}")
            
            if url:
                self.ketnoitieudung_url = url
                # Update the searching message with success
                self.crawled_specs_raw = self.crawled_specs_raw.replace(msg_searching, 
                    f"<div style='color: #28a745; font-size: 0.9em;'>✓ Tìm thấy sản phẩm trên Ketnoitieudung.vn</div>")
                
                # Verify URL matches product
                is_valid, reason = self._verify_url_matches_product(url)
                if is_valid == False:
                    self.ketnoitieudung_url = False  # Clear wrong URL
                    self.crawled_specs_raw += f"<div style='background: #f8d7da; border: 1px solid #f5c6cb; padding: 10px; margin: 10px 0; color: #721c24;'>❌ <b>Link bị từ chối & đã xóa:</b> {reason}</div>"
                    _logger.warning(f"[Ketnoitieudung] URL verification failed: {reason}")
                    return
            else:
                # Update with failure message
                self.crawled_specs_raw = self.crawled_specs_raw.replace(msg_searching,
                    f"<div style='color: #fd7e14;'>⚠ <b>Ketnoitieudung.vn:</b> {error or 'Không tìm thấy sản phẩm'}</div>")
                _logger.warning(f"[Ketnoitieudung] Product not found")
                return
        
        if url:
            _logger.info(f"[Ketnoitieudung] Parsing details from: {url}")
            specs, error = CrawlerUtils.parse_ketnoitieudung_details(url)
            _logger.info(f"[Ketnoitieudung] Parse result - Specs length: {len(specs) if specs else 0}, Error: {error}")
            
            if specs:
                # Specs already formatted with site name and header by format_specs_table()
                self.crawled_specs_raw = (self.crawled_specs_raw or "") + specs
            else:
                msg = f"<div style='color: #fd7e14;'>⚠ <b>Ketnoitieudung.vn:</b> {error or 'Lỗi tải dữ liệu'}</div>"
                self.crawled_specs_raw = (self.crawled_specs_raw or "") + msg
        
        # Auto-verify with GPT
        self._auto_verify_after_crawl()

    def action_crawl_visior(self):
        import logging
        _logger = logging.getLogger(__name__)
        
        self.ensure_one()
        _logger.info(f"[Visior] Starting crawl, current URL: {self.visior_url}")
        
        url = self.visior_url
        if not url and self.default_code:
            msg_searching = f"<div style='color: #6c757d; font-size: 0.9em;'>🔍 Đang tìm kiếm <b>{self.default_code}</b> trên Visior.vn...</div>"
            self.crawled_specs_raw = (self.crawled_specs_raw or "") + msg_searching
            
            _logger.info(f"[Visior] Searching for SKU: {self.default_code}, Name: {self.name}")
            url, error = CrawlerUtils.search_visior(self.default_code, self.name)
            _logger.info(f"[Visior] Search result - URL: {url}, Error: {error}")
            
            if url:
                self.visior_url = url
                self.crawled_specs_raw = self.crawled_specs_raw.replace(msg_searching,
                    f"<div style='color: #28a745; font-size: 0.9em;'>✓ Tìm thấy sản phẩm trên Visior.vn</div>")
                
                # Verify URL matches product
                is_valid, reason = self._verify_url_matches_product(url)
                if is_valid == False:
                    self.visior_url = False  # Clear wrong URL
                    self.crawled_specs_raw += f"<div style='background: #f8d7da; border: 1px solid #f5c6cb; padding: 10px; margin: 10px 0; color: #721c24;'>❌ <b>Link bị từ chối & đã xóa:</b> {reason}</div>"
                    _logger.warning(f"[Visior] URL verification failed: {reason}")
                    return
            else:
                self.crawled_specs_raw = self.crawled_specs_raw.replace(msg_searching,
                    f"<div style='color: #fd7e14;'>⚠ <b>Visior.vn:</b> {error or 'Không tìm thấy sản phẩm'}</div>")
                _logger.warning(f"[Visior] Product not found")
                return
        
        if url:
            _logger.info(f"[Visior] Parsing details from: {url}")
            specs, error = CrawlerUtils.parse_visior_details(url)
            _logger.info(f"[Visior] Parse result - Specs length: {len(specs) if specs else 0}, Error: {error}")
            
            if specs:
                self.crawled_specs_raw = (self.crawled_specs_raw or "") + f"<h3 style='color: #007bff;'>📦 Visior.vn</h3><p style='font-size: 0.85em; color: #6c757d;'>{url}</p>" + specs
            else:
                msg = f"<div style='color: #fd7e14;'>⚠ <b>Visior.vn:</b> {error or 'Lỗi tải dữ liệu'}</div>"
                self.crawled_specs_raw = (self.crawled_specs_raw or "") + msg
        
        # Auto-verify with GPT
        self._auto_verify_after_crawl()

    def action_crawl_thbvietnam(self):
        import logging
        _logger = logging.getLogger(__name__)
        
        self.ensure_one()
        _logger.info(f"[THB Vietnam] Starting crawl, current URL: {self.thbvietnam_url}")
        
        url = self.thbvietnam_url
        if not url and self.default_code:
            msg_searching = f"<div style='color: #6c757d; font-size: 0.9em;'>🔍 Đang tìm kiếm <b>{self.default_code}</b> trên THB Vietnam...</div>"
            self.crawled_specs_raw = (self.crawled_specs_raw or "") + msg_searching
            
            _logger.info(f"[THB Vietnam] Searching for SKU: {self.default_code}, Name: {self.name}")
            url, error = CrawlerUtils.search_thbvietnam(self.default_code, self.name)
            _logger.info(f"[THB Vietnam] Search result - URL: {url}, Error: {error}")
            
            if url:
                self.thbvietnam_url = url
                self.crawled_specs_raw = self.crawled_specs_raw.replace(msg_searching,
                    f"<div style='color: #28a745; font-size: 0.9em;'>✓ Tìm thấy sản phẩm trên THB Vietnam</div>")
                
                # Verify URL matches product
                is_valid, reason = self._verify_url_matches_product(url)
                if is_valid == False:
                    self.thbvietnam_url = False  # Clear wrong URL
                    self.crawled_specs_raw += f"<div style='background: #f8d7da; border: 1px solid #f5c6cb; padding: 10px; margin: 10px 0; color: #721c24;'>❌ <b>Link bị từ chối & đã xóa:</b> {reason}</div>"
                    _logger.warning(f"[THB Vietnam] URL verification failed: {reason}")
                    return
            else:
                self.crawled_specs_raw = self.crawled_specs_raw.replace(msg_searching,
                    f"<div style='color: #fd7e14;'>⚠ <b>THB Vietnam:</b> {error or 'Không tìm thấy sản phẩm'}</div>")
                _logger.warning(f"[THB Vietnam] Product not found")
                return
        
        if url:
            _logger.info(f"[THB Vietnam] Parsing details from: {url}")
            specs, error = CrawlerUtils.parse_thbvietnam_details(url)
            _logger.info(f"[THB Vietnam] Parse result - Specs length: {len(specs) if specs else 0}, Error: {error}")
            
            if specs:
                self.crawled_specs_raw = (self.crawled_specs_raw or "") + f"<h3 style='color: #007bff;'>📦 THB Vietnam</h3><p style='font-size: 0.85em; color: #6c757d;'>{url}</p>" + specs
            else:
                msg = f"<div style='color: #fd7e14;'>⚠ <b>THB Vietnam:</b> {error or 'Lỗi tải dữ liệu'}</div>"
                self.crawled_specs_raw = (self.crawled_specs_raw or "") + msg
        
        # Auto-verify with GPT
        self._auto_verify_after_crawl()

    def action_crawl_mecsu(self):
        import logging
        _logger = logging.getLogger(__name__)
        
        self.ensure_one()
        _logger.info(f"[Mecsu] Starting crawl, current URL: {self.mecsu_url}")
        
        url = self.mecsu_url
        if not url and self.default_code:
            msg_searching = f"<div style='color: #6c757d; font-size: 0.9em;'>🔍 Đang tìm kiếm <b>{self.default_code}</b> trên Mecsu.vn...</div>"
            self.crawled_specs_raw = (self.crawled_specs_raw or "") + msg_searching
            
            _logger.info(f"[Mecsu] Searching for SKU: {self.default_code}, Name: {self.name}")
            url, error = CrawlerUtils.search_mecsu(self.default_code, self.name)
            _logger.info(f"[Mecsu] Search result - URL: {url}, Error: {error}")
            
            if url:
                self.mecsu_url = url
                self.crawled_specs_raw = self.crawled_specs_raw.replace(msg_searching,
                    f"<div style='color: #28a745; font-size: 0.9em;'>✓ Tìm thấy sản phẩm trên Mecsu.vn</div>")
                
                # Verify URL matches product
                is_valid, reason = self._verify_url_matches_product(url)
                if is_valid == False:
                    self.mecsu_url = False  # Clear wrong URL
                    self.crawled_specs_raw += f"<div style='background: #f8d7da; border: 1px solid #f5c6cb; padding: 10px; margin: 10px 0; color: #721c24;'>❌ <b>Link bị từ chối & đã xóa:</b> {reason}</div>"
                    _logger.warning(f"[Mecsu] URL verification failed: {reason}")
                    return
            else:
                self.crawled_specs_raw = self.crawled_specs_raw.replace(msg_searching,
                    f"<div style='color: #fd7e14;'>⚠ <b>Mecsu.vn:</b> {error or 'Không tìm thấy sản phẩm'}</div>")
                _logger.warning(f"[Mecsu] Product not found")
                return
        
        if url:
            _logger.info(f"[Mecsu] Parsing details from: {url}")
            specs, error = CrawlerUtils.parse_mecsu_details(url)
            _logger.info(f"[Mecsu] Parse result - Specs length: {len(specs) if specs else 0}, Error: {error}")
            
            if specs:
                self.crawled_specs_raw = (self.crawled_specs_raw or "") + f"<h3 style='color: #007bff;'>📦 Mecsu.vn</h3><p style='font-size: 0.85em; color: #6c757d;'>{url}</p>" + specs
            else:
                msg = f"<div style='color: #fd7e14;'>⚠ <b>Mecsu.vn:</b> {error or 'Lỗi tải dữ liệu'}</div>"
                self.crawled_specs_raw = (self.crawled_specs_raw or "") + msg
        
        # Auto-verify with GPT
        self._auto_verify_after_crawl()

    def action_crawl_milwaukee(self):
        import logging
        _logger = logging.getLogger(__name__)
        
        self.ensure_one()
        _logger.info(f"[Milwaukee] Starting crawl, current URL: {self.milwaukee_url}")
        
        url = self.milwaukee_url
        if not url and self.default_code:
            msg_searching = f"<div style='color: #6c757d; font-size: 0.9em;'>🔍 Đang tìm kiếm <b>{self.default_code}</b> trên Milwaukee...</div>"
            self.crawled_specs_raw = (self.crawled_specs_raw or "") + msg_searching
            
            _logger.info(f"[Milwaukee] Searching for SKU: {self.default_code}, Name: {self.name}")
            url, error = CrawlerUtils.search_milwaukee(self.default_code, self.name)
            _logger.info(f"[Milwaukee] Search result - URL: {url}, Error: {error}")
            
            if url:
                self.milwaukee_url = url
                self.crawled_specs_raw = self.crawled_specs_raw.replace(msg_searching,
                    f"<div style='color: #28a745; font-size: 0.9em;'>✓ Tìm thấy sản phẩm trên Milwaukee</div>")
                
                # Verify URL matches product
                is_valid, reason = self._verify_url_matches_product(url)
                if is_valid == False:
                    self.milwaukee_url = False  # Clear wrong URL
                    self.crawled_specs_raw += f"<div style='background: #f8d7da; border: 1px solid #f5c6cb; padding: 10px; margin: 10px 0; color: #721c24;'>❌ <b>Link bị từ chối & đã xóa:</b> {reason}</div>"
                    _logger.warning(f"[Milwaukee] URL verification failed: {reason}")
                    return
            else:
                self.crawled_specs_raw = self.crawled_specs_raw.replace(msg_searching,
                    f"<div style='color: #fd7e14;'>⚠ <b>Milwaukee:</b> {error or 'Không tìm thấy sản phẩm'}</div>")
                _logger.warning(f"[Milwaukee] Product not found")
                return
        
        if url:
            _logger.info(f"[Milwaukee] Parsing details from: {url}")
            specs, error = CrawlerUtils.parse_milwaukee_details(url)
            _logger.info(f"[Milwaukee] Parse result - Specs length: {len(specs) if specs else 0}, Error: {error}")
            
            if specs:
                # Specs already formatted
                self.crawled_specs_raw = (self.crawled_specs_raw or "") + specs
            else:
                msg = f"<div style='color: #fd7e14;'>⚠ <b>Milwaukee:</b> {error or 'Lỗi tải dữ liệu'}</div>"
                self.crawled_specs_raw = (self.crawled_specs_raw or "") + msg
        
        # Auto-verify with GPT
        self._auto_verify_after_crawl()

    def action_crawl_bosch(self):
        import logging
        _logger = logging.getLogger(__name__)
        
        self.ensure_one()
        _logger.info(f"[Bosch] Starting crawl, current URL: {self.bosch_url}")
        
        url = self.bosch_url
        if not url and self.default_code:
            msg_searching = f"<div style='color: #6c757d; font-size: 0.9em;'>🔍 Đang tìm kiếm <b>{self.default_code}</b> trên Bosch...</div>"
            self.crawled_specs_raw = (self.crawled_specs_raw or "") + msg_searching
            
            _logger.info(f"[Bosch] Searching for SKU: {self.default_code}, Name: {self.name}")
            url, error = CrawlerUtils.search_bosch(self.default_code, self.name)
            _logger.info(f"[Bosch] Search result - URL: {url}, Error: {error}")
            
            if url:
                self.bosch_url = url
                self.crawled_specs_raw = self.crawled_specs_raw.replace(msg_searching,
                    f"<div style='color: #28a745; font-size: 0.9em;'>✓ Tìm thấy sản phẩm trên Bosch</div>")
                
                # Verify URL matches product
                is_valid, reason = self._verify_url_matches_product(url)
                if is_valid == False:
                    self.bosch_url = False  # Clear wrong URL
                    self.crawled_specs_raw += f"<div style='background: #f8d7da; border: 1px solid #f5c6cb; padding: 10px; margin: 10px 0; color: #721c24;'>❌ <b>Link bị từ chối & đã xóa:</b> {reason}</div>"
                    _logger.warning(f"[Bosch] URL verification failed: {reason}")
                    return
            else:
                self.crawled_specs_raw = self.crawled_specs_raw.replace(msg_searching,
                    f"<div style='color: #fd7e14;'>⚠ <b>Bosch:</b> {error or 'Không tìm thấy sản phẩm'}</div>")
                _logger.warning(f"[Bosch] Product not found")
                return
        
        if url:
            _logger.info(f"[Bosch] Parsing details from: {url}")
            specs, error = CrawlerUtils.parse_bosch_details(url)
            _logger.info(f"[Bosch] Parse result - Specs length: {len(specs) if specs else 0}, Error: {error}")
            
            if specs:
                self.crawled_specs_raw = (self.crawled_specs_raw or "") + specs
            else:
                msg = f"<div style='color: #fd7e14;'>⚠ <b>Bosch:</b> {error or 'Lỗi tải dữ liệu'}</div>"
                self.crawled_specs_raw = (self.crawled_specs_raw or "") + msg
        
        # Auto-verify with GPT
        self._auto_verify_after_crawl()

    def action_crawl_all(self):
        import logging
        _logger = logging.getLogger(__name__)
        
        for record in self:
            _logger.info(f"=== Starting crawl for product: {record.name} (ID: {record.id}) ===")
            _logger.info(f"Product default_code: {record.default_code}")
            
            # Check if product has default_code
            if not record.default_code:
                record.crawled_specs_raw = """
                    <div style='background: #fff3cd; padding: 15px; border-radius: 5px; border-left: 4px solid #ffc107;'>
                        <h3 style='color: #856404; margin: 0 0 10px 0;'>⚠️ Không thể tìm kiếm</h3>
                        <p style='margin: 0; color: #856404;'>Sản phẩm chưa có <b>Mã nội bộ (Internal Reference)</b>.</p>
                        <p style='margin: 5px 0 0 0; color: #856404;'>Vui lòng thêm mã sản phẩm trước khi crawl.</p>
                    </div>
                """
                _logger.warning(f"Product {record.name} has no default_code, skipping crawl")
                continue
            
            # --- LOGIC OPTIMIZATION START ---
            name_lower = (record.name or "").lower()
            name_original = record.name or ""
            
            # Identify Product Type/Brand
            is_milwaukee = "milwaukee" in name_lower or "m12" in name_lower or "m18" in name_lower or "mx" in name_lower
            is_bosch = "bosch" in name_lower or "gba" in name_lower or "procore" in name_lower
            
            # Keywords for fasteners
            keywords_fastener = ["bu lông", "ốc", "vít", "bulong", "oc vit", "đai ốc", "long đền", "tán", "rive"]
            is_fastener = any(k in name_lower for k in keywords_fastener)

            # Determine which sites to crawl
            run_milwaukee = True
            run_bosch = True
            run_resellers = True # Ketnoitieudung, Visior, THB, Mecsu
            
            # Brand exclusion logic
            if is_milwaukee:
                run_bosch = False
                _logger.info(f"Product '{name_original}' identified as Milwaukee. Skipping Bosch.")
                
            if is_bosch:
                run_milwaukee = False
                _logger.info(f"Product '{name_original}' identified as Bosch. Skipping Milwaukee.")
                
            # Fastener exclusive logic (User request: "nếu là bu lông, ốc vít, thì chỉ search ở mecsu và kết nối tiêu dùng")
            run_mecsu = True
            run_ketnoitieudung = True
            run_visior = True
            run_thb = True

            if is_fastener:
                run_milwaukee = False
                run_bosch = False
                run_visior = False
                run_thb = False
                _logger.info(f"Product '{name_original}' identified as Fastener. Crawling ONLY Mecsu & Ketnoitieudung.")
            
            # --- LOGIC OPTIMIZATION END ---

            # Clear previous specs and add header
            record.crawled_specs_raw = f"""
                <div style='background: #f8f9fa; padding: 15px; border-radius: 5px; margin-bottom: 15px;'>
                    <h2 style='color: #495057; margin: 0 0 10px 0;'>🔍 Kết quả tìm kiếm</h2>
                    <p style='margin: 0; color: #6c757d;'>Mã sản phẩm: <b>{record.default_code}</b></p>
                    <p style='margin: 5px 0 0 0; color: #6c757d; font-size: 0.9em;'>Đang tìm kiếm...</p>
                </div>
            """
            
            # 1. Official Sites
            if run_milwaukee:
                try:
                    _logger.info("Crawling Milwaukee...")
                    record.action_crawl_milwaukee()
                except Exception as e:
                    _logger.error(f"Error crawling Milwaukee: {e}")
                    record.crawled_specs_raw += f"<div style='color: red;'>Lỗi Milwaukee: {str(e)}</div>"

            if run_bosch:
                try:
                    _logger.info("Crawling Bosch...")
                    record.action_crawl_bosch()
                except Exception as e:
                    _logger.error(f"Error crawling Bosch: {e}")
                    record.crawled_specs_raw += f"<div style='color: red;'>Lỗi Bosch: {str(e)}</div>"

            # 2. Reseller Sites
            if run_ketnoitieudung:
                try:
                    _logger.info("Crawling Ketnoitieudung...")
                    record.action_crawl_ketnoitieudung()
                except Exception as e:
                    _logger.error(f"Error crawling Ketnoitieudung: {e}")
                    record.crawled_specs_raw += f"<div style='color: red;'>Lỗi Ketnoitieudung: {str(e)}</div>"
            
            if run_visior:
                try:
                    _logger.info("Crawling Visior...")
                    record.action_crawl_visior()
                except Exception as e:
                    _logger.error(f"Error crawling Visior: {e}")
                    record.crawled_specs_raw += f"<div style='color: red;'>Lỗi Visior: {str(e)}</div>"
            
            if run_thb:
                try:
                    _logger.info("Crawling THB Vietnam...")
                    record.action_crawl_thbvietnam()
                except Exception as e:
                    _logger.error(f"Error crawling THB Vietnam: {e}")
                    record.crawled_specs_raw += f"<div style='color: red;'>Lỗi THB: {str(e)}</div>"
            
            if run_mecsu:
                try:
                    _logger.info("Crawling Mecsu...")
                    record.action_crawl_mecsu()
                except Exception as e:
                    _logger.error(f"Error crawling Mecsu: {e}")
                    record.crawled_specs_raw += f"<div style='color: red;'>Lỗi Mecsu: {str(e)}</div>"
            
            _logger.info(f"=== Finished crawl for product: {record.name} ===")
