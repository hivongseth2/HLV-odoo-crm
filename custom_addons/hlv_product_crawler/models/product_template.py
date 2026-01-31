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
    
    
    # Queue System Fields
    crawl_status = fields.Selection([
        ('new', 'Mới'),
        ('pending', 'Chờ xử lý'),
        ('done', 'Hoàn thành'),
        ('failed', 'Lỗi'),
        ('skipped', 'Đã bỏ qua')
    ], string="Trạng thái Crawl", default='new', copy=False)
    
    last_crawl = fields.Datetime(string="Crawl lần cuối", readonly=True)
    
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

    def _crawl_site_generic(self, site_key, site_name, search_func, parse_func, url_field):
        """
        Generic crawl logic that returns (html_content, error_msg).
        DOES NOT write to crawled_specs_raw to avoid excessive DB writes/attachment IO.
        """
        import logging
        _logger = logging.getLogger(__name__)
        
        current_url = getattr(self, url_field)
        _logger.info(f"[{site_name}] Starting crawl, current URL: {current_url}")
        
        url = current_url
        html_output = ""
        
        # 1. Search if no URL
        if not url and self.default_code:
            _logger.info(f"[{site_name}] Searching for SKU: {self.default_code}, Name: {self.name}")
            
            # Pass both SKU and product name to search function
            # Note: All search functions in CrawlerUtils mostly take (sku, name)
            # mecsu takes (sku, name)
            # others usually take (sku) but wrappers might vary. 
            # Let's assume standard signature (sku, name) or handle exceptions if needed.
            # Checked parsers: they all seem to accept (sku, name) or (sku). 
            # Python is forgiving with extra args if func definition accepts *args, but let's check.
            # CrawlerUtils matches: 
            # search_ketnoitieudung(sku, name)
            # search_visior(sku, name)
            # search_thbvietnam(sku, name)
            # search_mecsu(sku, name)
            # search_milwaukee(sku, name)
            # search_bosch(sku, name)
            # All consistent.
            
            found_url, error = search_func(self.default_code, self.name)
            _logger.info(f"[{site_name}] Search result - URL: {found_url}, Error: {error}")
            
            if found_url:
                # Update URL field immediately (Char field write is cheap)
                setattr(self, url_field, found_url)
                url = found_url
                
                # Verify URL matches product
                is_valid, reason = self._verify_url_matches_product(url)
                if is_valid == False:
                    setattr(self, url_field, False) # Clear wrong URL
                    return f"<div style='background: #f8d7da; border: 1px solid #f5c6cb; padding: 10px; margin: 10px 0; color: #721c24;'>❌ <b>{site_name}: Link bị từ chối & đã xóa:</b> {reason}</div>", "URL rejected"
            else:
                return f"<div style='color: #fd7e14;'>⚠ <b>{site_name}:</b> {error or 'Không tìm thấy sản phẩm'}</div>", error or "Not found"
        
        # 2. Parse if URL exists
        if url:
            _logger.info(f"[{site_name}] Parsing details from: {url}")
            specs, error = parse_func(url)
            _logger.info(f"[{site_name}] Parse result - Specs length: {len(specs) if specs else 0}, Error: {error}")
            
            if specs:
                # Add Site Header
                header = f"<h3 style='color: #007bff;'>📦 {site_name}</h3><p style='font-size: 0.85em; color: #6c757d;'>{url}</p>"
                # Check if specs already has header (Ketnoitieudung format_specs_table might add one?)
                # Based on previous code:
                # ketnoitieudung: "Specs already formatted with site name and header"
                # milwaukee: "Specs already formatted"
                # Others: Manually added header.
                
                # We need to handle this specific formatting nuance.
                if site_key in ['ketnoitieudung', 'milwaukee']:
                    return specs, None
                else:
                    return header + specs, None
            else:
                return f"<div style='color: #fd7e14;'>⚠ <b>{site_name}:</b> {error or 'Lỗi tải dữ liệu'}</div>", error or "Parse error"
        
        return "", "No URL"

    def action_crawl_ketnoitieudung(self):
        self.ensure_one()
        specs, _ = self._crawl_site_generic('ketnoitieudung', 'Ketnoitieudung.vn', 
            CrawlerUtils.search_ketnoitieudung, CrawlerUtils.parse_ketnoitieudung_details, 'ketnoitieudung_url')
        if specs:
            self.crawled_specs_raw = (self.crawled_specs_raw or "") + specs
            self._auto_verify_after_crawl()

    def action_crawl_visior(self):
        self.ensure_one()
        specs, _ = self._crawl_site_generic('visior', 'Visior.vn', 
            CrawlerUtils.search_visior, CrawlerUtils.parse_visior_details, 'visior_url')
        if specs:
            self.crawled_specs_raw = (self.crawled_specs_raw or "") + specs
            self._auto_verify_after_crawl()

    def action_crawl_thbvietnam(self):
        self.ensure_one()
        specs, _ = self._crawl_site_generic('thbvietnam', 'THB Vietnam', 
            CrawlerUtils.search_thbvietnam, CrawlerUtils.parse_thbvietnam_details, 'thbvietnam_url')
        if specs:
            self.crawled_specs_raw = (self.crawled_specs_raw or "") + specs
            self._auto_verify_after_crawl()

    def action_crawl_mecsu(self):
        self.ensure_one()
        specs, _ = self._crawl_site_generic('mecsu', 'Mecsu.vn', 
            CrawlerUtils.search_mecsu, CrawlerUtils.parse_mecsu_details, 'mecsu_url')
        if specs:
            self.crawled_specs_raw = (self.crawled_specs_raw or "") + specs
            self._auto_verify_after_crawl()

    def action_crawl_milwaukee(self):
        self.ensure_one()
        specs, _ = self._crawl_site_generic('milwaukee', 'Milwaukee', 
            CrawlerUtils.search_milwaukee, CrawlerUtils.parse_milwaukee_details, 'milwaukee_url')
        if specs:
            self.crawled_specs_raw = (self.crawled_specs_raw or "") + specs
            self._auto_verify_after_crawl()

    def action_crawl_bosch(self):
        self.ensure_one()
        specs, _ = self._crawl_site_generic('bosch', 'Bosch', 
            CrawlerUtils.search_bosch, CrawlerUtils.parse_bosch_details, 'bosch_url')
        if specs:
            self.crawled_specs_raw = (self.crawled_specs_raw or "") + specs
            self._auto_verify_after_crawl()

    def action_add_to_crawl_queue(self):
        """Action for Server Action to add products to queue"""
        for record in self:
            if record.crawl_status in ['done', 'skipped', 'failed', 'new']:
                record.crawl_status = 'pending'
    
    @api.model
    def cron_crawl_batch(self):
        """Scheduled Action to crawl pending products"""
        # Check global setting
        auto_crawl = self.env['ir.config_parameter'].sudo().get_param('product_crawler.auto_crawl')
        if not auto_crawl:
            return
            
        # Get Batch Size
        try:
            batch_size = int(self.env['ir.config_parameter'].sudo().get_param('product_crawler.batch_size', '10'))
        except:
            batch_size = 10
            
        # Find pending products
        products = self.search([('crawl_status', '=', 'pending')], limit=batch_size, order='write_date asc')
        
        if not products:
            return

        import logging
        _logger = logging.getLogger(__name__)
        _logger.info(f"[Crawler Cron] Processing batch of {len(products)} products...")
        
        for product in products:
            try:
                # Use the optimized generic crawl
                # This will create ONE write to DB per product
                product.action_crawl_and_analyze()
                
                product.write({
                    'crawl_status': 'done',
                    'last_crawl': fields.Datetime.now()
                })
                
                # Commit after each product to save progress (and prevent transaction timeouts)
                self.env.cr.commit()
                
            except Exception as e:
                _logger.error(f"[Crawler Cron] Error processing ID {product.id}: {e}")
                product.write({'crawl_status': 'failed'})
                self.env.cr.commit()
                
    def action_crawl_all(self):
        import logging
        _logger = logging.getLogger(__name__)
        
        for record in self:
            _logger.info(f"=== Starting crawl for product: {record.name} (ID: {record.id}) ===")
            
            if not record.default_code:
                record.crawled_specs_raw = """
                    <div style='background: #fff3cd; padding: 15px; border-radius: 5px; border-left: 4px solid #ffc107;'>
                        <h3 style='color: #856404; margin: 0 0 10px 0;'>⚠️ Không thể tìm kiếm</h3>
                        <p style='margin: 0; color: #856404;'>Sản phẩm chưa có <b>Mã nội bộ (Internal Reference)</b>.</p>
                    </div>"""
                continue
            
            # --- LOGIC OPTIMIZATION START ---
            name_lower = (record.name or "").lower()
            name_original = record.name or ""
            
            is_milwaukee = "milwaukee" in name_lower or "m12" in name_lower or "m18" in name_lower or "mx" in name_lower
            is_bosch = "bosch" in name_lower or "gba" in name_lower or "procore" in name_lower
            keywords_fastener = ["bu lông", "ốc", "vít", "bulong", "oc vit", "đai ốc", "long đền", "tán", "rive"]
            is_fastener = any(k in name_lower for k in keywords_fastener)

            run_milwaukee = True
            run_bosch = True
            run_resellers = True
            run_mecsu = True
            run_ketnoitieudung = True
            run_visior = True
            run_thb = True
            
            if is_milwaukee:
                run_bosch = False
            if is_bosch:
                run_milwaukee = False

            if is_fastener:
                run_milwaukee = False
                run_bosch = False
                run_visior = False
                run_thb = False
                _logger.info(f"Product '{name_original}' identified as Fastener. Crawling ONLY Mecsu & Ketnoitieudung.")
            
            # --- COLLECT DATA (BUFFERING) ---
            accumulated_html = f"""
                <div style='background: #f8f9fa; padding: 15px; border-radius: 5px; margin-bottom: 15px;'>
                    <h2 style='color: #495057; margin: 0 0 10px 0;'>🔍 Kết quả tìm kiếm</h2>
                    <p style='margin: 0; color: #6c757d;'>Mã sản phẩm: <b>{record.default_code}</b></p>
                </div>
            """
            
            # 1. Official Sites
            if run_milwaukee:
                html, _ = record._crawl_site_generic('milwaukee', 'Milwaukee', 
                    CrawlerUtils.search_milwaukee, CrawlerUtils.parse_milwaukee_details, 'milwaukee_url')
                accumulated_html += html

            if run_bosch:
                html, _ = record._crawl_site_generic('bosch', 'Bosch', 
                    CrawlerUtils.search_bosch, CrawlerUtils.parse_bosch_details, 'bosch_url')
                accumulated_html += html

            # 2. Reseller Sites
            if run_ketnoitieudung:
                html, _ = record._crawl_site_generic('ketnoitieudung', 'Ketnoitieudung.vn', 
                    CrawlerUtils.search_ketnoitieudung, CrawlerUtils.parse_ketnoitieudung_details, 'ketnoitieudung_url')
                accumulated_html += html
            
            if run_visior:
                html, _ = record._crawl_site_generic('visior', 'Visior.vn', 
                    CrawlerUtils.search_visior, CrawlerUtils.parse_visior_details, 'visior_url')
                accumulated_html += html
            
            if run_thb:
                html, _ = record._crawl_site_generic('thbvietnam', 'THB Vietnam', 
                    CrawlerUtils.search_thbvietnam, CrawlerUtils.parse_thbvietnam_details, 'thbvietnam_url')
                accumulated_html += html
            
            if run_mecsu:
                html, _ = record._crawl_site_generic('mecsu', 'Mecsu.vn', 
                    CrawlerUtils.search_mecsu, CrawlerUtils.parse_mecsu_details, 'mecsu_url')
                accumulated_html += html
            
            # --- FINAL WRITE ---
            record.crawled_specs_raw = accumulated_html
            
            # Verify after all writes are done
            record._auto_verify_after_crawl()
            
            _logger.info(f"=== Finished crawl for product: {record.name} ===")
