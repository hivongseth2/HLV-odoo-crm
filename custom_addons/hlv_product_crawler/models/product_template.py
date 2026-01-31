from odoo import models, fields, api, _
from odoo.exceptions import UserError
from .crawler_parsers import CrawlerUtils

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    ketnoitieudung_url = fields.Char(string="Ketnoitieudung URL", help="URL to crawl technical specs from ketnoitieudung.vn")
    visior_url = fields.Char(string="Visior URL", help="URL to crawl technical specs from visior.vn")
    thbvietnam_url = fields.Char(string="THB Vietnam URL", help="URL to crawl technical specs from thbvietnam.com")
    mecsu_url = fields.Char(string="Mecsu URL", help="URL to crawl technical specs from mecsu.vn")
    milwaukee_url = fields.Char(string="Milwaukee URL", help="URL to crawl technical specs from milwaukeetool.com.vn")
    bosch_url = fields.Char(string="Bosch URL", help="URL to crawl technical specs from vn.bosch-pt.com")
    
    crawled_specs = fields.Text(string="Crawled Specifications")

    # AI QC Fields
    ai_verify_score = fields.Integer(string="AI QC Score", readonly=True, help="Quality Control Score (0-100) from Mr. GPT")
    ai_verify_analysis = fields.Html(string="Mr. GPT Analysis", readonly=True)
    ai_last_verify_date = fields.Datetime(string="Last Verified", readonly=True)

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
        specs = self.crawled_specs or "No specs crawled yet."
        
        prompt = f"""You are Mr. GPT, a strict Quality Control expert for Industrial Tools.
Analyze the following crawled data for product SKU: {sku}, Name: {name}.
Data:
{specs}

Task: Verify if this data technically matches the product.
Rules:
1. Ignore minor formatting issues.
2. Focus on Specs (Voltage, RPM, Weight, Model Number).
3. If Specs are missing or clearly belong to another product (e.g. M12 vs M18), Lower the score.
4. If Specs are duplicated but correct, minor penalty.
5. Return ONLY valid JSON in format: {{"score": 0-100, "reason": "HTML formatted analysis string"}}."""

        import requests
        import json
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        data = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a helpful QC assistant returning JSON."},
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
        
        prompt = f"""You are Mr. GPT, a product URL verification expert.

Product Info:
- SKU: {sku}
- Product Name: {name}

Found URL: {url}

Task: Analyze if this URL likely contains specs for the CORRECT product.
Check:
1. Domain match (e.g., Milwaukee product should be on milwaukeetool.com, not bosch-pt.com)
2. URL path/slug contains SKU, brand, or model identifiers
3. Product type consistency

Return ONLY valid JSON: {{"is_correct": true/false, "confidence": 0-100, "reason": "brief explanation why URL matches or doesn't match"}}

Examples:
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
                {"role": "system", "content": "You are a helpful URL verification assistant returning JSON."},
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
        if not self.crawled_specs:
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
                ✅ <strong>Mr. GPT Verified ({score}/100)</strong> - Data quality looks good!
            </div>"""
            self.crawled_specs += badge
        elif score >= 50:
            badge = f"""
            <div style='background: #fff3cd; border: 1px solid #ffeaa7; border-radius: 4px; padding: 10px; margin: 10px 0; color: #856404;'>
                ⚠️ <strong>Possible Mismatch ({score}/100)</strong> - Please verify manually. {analysis[:100]}...
            </div>"""
            self.crawled_specs += badge
        else:
            # Score < 50: Replace specs with error message
            self.crawled_specs = f"""
            <div style='background: #f8d7da; border: 1px solid #f5c6cb; border-radius: 4px; padding: 15px; margin: 10px 0; color: #721c24;'>
                ❌ <strong>GPT Rejected: Wrong Product Detected ({score}/100)</strong>
                <p>{analysis}</p>
                <p><em>The crawled data does not match this product. Please check the URL or SKU.</em></p>
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
                'title': _('Mr. GPT Finished'),
                'message': f"Verification Score: {self.ai_verify_score}/100",
                'sticky': False,
                'type': 'success' if self.ai_verify_score >= 80 else 'warning',
            }
        }

    def action_consolidate_specs(self):
        """Consolidate all crawled specs from multiple sources into one clean document using GPT"""
        self.ensure_one()
        
        api_key = self.env['ir.config_parameter'].sudo().get_param('product_crawler.openai_api_key')
        if not api_key:
            raise UserError(_("OpenAI API Key is not configured in Settings."))
        
        if not self.crawled_specs:
            raise UserError(_("No crawled specs to consolidate. Please crawl data first."))
        
        model = self.env['ir.config_parameter'].sudo().get_param('product_crawler.openai_model') or 'gpt-4o-mini'
        
        sku = self.default_code or "N/A"
        name = self.name or "N/A"
        raw_data = self.crawled_specs
        
        prompt = f"""You are Mr. GPT, a professional technical writer for industrial tools.

Product: {name} (SKU: {sku})

Raw crawled data from multiple sources:
{raw_data}

Task: Consolidate this raw data into ONE clean, professional specification document.

Rules:
1. Merge duplicate information (keep most accurate values)
2. Organize into sections: Overview, Technical Specifications, Features, Applications
3. Remove all crawl metadata (source headers, search messages, error messages, verification badges)
4. Keep only actual product specifications and features
5. Format as clean HTML with proper headings and tables
6. If conflicting data exists, use majority vote or most detailed source
7. Return ONLY the consolidated HTML content, no extra text

Output format:
<h2>Product Overview</h2>
<p>Brief description...</p>

<h2>Technical Specifications</h2>
<table>...</table>

<h2>Key Features</h2>
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
                {"role": "system", "content": "You are a helpful technical writing assistant."},
                {"role": "user", "content": prompt}
            ]
        }
        
        try:
            response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=data, timeout=60)
            response.raise_for_status()
            result = response.json()
            
            consolidated = result['choices'][0]['message']['content']
            
            # Replace crawled_specs with consolidated version
            self.crawled_specs = f"""
            <div style='background: #cfe2ff; border: 1px solid #9ec5fe; padding: 10px; margin: 10px 0; color: #052c65;'>
                🤖 <b>Consolidated by Mr. GPT</b> - This document was auto-generated from multiple sources
            </div>
            {consolidated}
            """
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Mr. GPT Consolidation Complete'),
                    'message': "Specs have been consolidated into a single clean document.",
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
            self.crawled_specs = (self.crawled_specs or "") + msg_searching
            
            _logger.info(f"[Ketnoitieudung] Searching for SKU: {self.default_code}, Name: {self.name}")
            # Pass both SKU and product name
            url, error = CrawlerUtils.search_ketnoitieudung(self.default_code, self.name)
            _logger.info(f"[Ketnoitieudung] Search result - URL: {url}, Error: {error}")
            
            if url:
                self.ketnoitieudung_url = url
                # Update the searching message with success
                self.crawled_specs = self.crawled_specs.replace(msg_searching, 
                    f"<div style='color: #28a745; font-size: 0.9em;'>✓ Tìm thấy sản phẩm trên Ketnoitieudung.vn</div>")
                
                # Verify URL matches product
                is_valid, reason = self._verify_url_matches_product(url)
                if is_valid == False:
                    self.ketnoitieudung_url = False  # Clear wrong URL
                    self.crawled_specs += f"<div style='background: #f8d7da; border: 1px solid #f5c6cb; padding: 10px; margin: 10px 0; color: #721c24;'>❌ <b>URL rejected & cleared:</b> {reason}</div>"
                    _logger.warning(f"[Ketnoitieudung] URL verification failed: {reason}")
                    return
            else:
                # Update with failure message
                self.crawled_specs = self.crawled_specs.replace(msg_searching,
                    f"<div style='color: #fd7e14;'>⚠ <b>Ketnoitieudung.vn:</b> {error or 'Không tìm thấy sản phẩm'}</div>")
                _logger.warning(f"[Ketnoitieudung] Product not found")
                return
        
        if url:
            _logger.info(f"[Ketnoitieudung] Parsing details from: {url}")
            specs, error = CrawlerUtils.parse_ketnoitieudung_details(url)
            _logger.info(f"[Ketnoitieudung] Parse result - Specs length: {len(specs) if specs else 0}, Error: {error}")
            
            if specs:
                # Specs already formatted with site name and header by format_specs_table()
                self.crawled_specs = (self.crawled_specs or "") + specs
            else:
                msg = f"<div style='color: #fd7e14;'>⚠ <b>Ketnoitieudung.vn:</b> {error or 'Lỗi tải dữ liệu'}</div>"
                self.crawled_specs = (self.crawled_specs or "") + msg
        
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
            self.crawled_specs = (self.crawled_specs or "") + msg_searching
            
            _logger.info(f"[Visior] Searching for SKU: {self.default_code}, Name: {self.name}")
            url, error = CrawlerUtils.search_visior(self.default_code, self.name)
            _logger.info(f"[Visior] Search result - URL: {url}, Error: {error}")
            
            if url:
                self.visior_url = url
                self.crawled_specs = self.crawled_specs.replace(msg_searching,
                    f"<div style='color: #28a745; font-size: 0.9em;'>✓ Tìm thấy sản phẩm trên Visior.vn</div>")
                
                # Verify URL matches product
                is_valid, reason = self._verify_url_matches_product(url)
                if is_valid == False:
                    self.visior_url = False  # Clear wrong URL
                    self.crawled_specs += f"<div style='background: #f8d7da; border: 1px solid #f5c6cb; padding: 10px; margin: 10px 0; color: #721c24;'>❌ <b>URL rejected & cleared:</b> {reason}</div>"
                    _logger.warning(f"[Visior] URL verification failed: {reason}")
                    return
            else:
                self.crawled_specs = self.crawled_specs.replace(msg_searching,
                    f"<div style='color: #fd7e14;'>⚠ <b>Visior.vn:</b> {error or 'Không tìm thấy sản phẩm'}</div>")
                _logger.warning(f"[Visior] Product not found")
                return
        
        if url:
            _logger.info(f"[Visior] Parsing details from: {url}")
            specs, error = CrawlerUtils.parse_visior_details(url)
            _logger.info(f"[Visior] Parse result - Specs length: {len(specs) if specs else 0}, Error: {error}")
            
            if specs:
                self.crawled_specs = (self.crawled_specs or "") + f"<h3 style='color: #007bff;'>📦 Visior.vn</h3><p style='font-size: 0.85em; color: #6c757d;'>{url}</p>" + specs
            else:
                msg = f"<div style='color: #fd7e14;'>⚠ <b>Visior.vn:</b> {error or 'Lỗi tải dữ liệu'}</div>"
                self.crawled_specs = (self.crawled_specs or "") + msg
        
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
            self.crawled_specs = (self.crawled_specs or "") + msg_searching
            
            _logger.info(f"[THB Vietnam] Searching for SKU: {self.default_code}, Name: {self.name}")
            url, error = CrawlerUtils.search_thbvietnam(self.default_code, self.name)
            _logger.info(f"[THB Vietnam] Search result - URL: {url}, Error: {error}")
            
            if url:
                self.thbvietnam_url = url
                self.crawled_specs = self.crawled_specs.replace(msg_searching,
                    f"<div style='color: #28a745; font-size: 0.9em;'>✓ Tìm thấy sản phẩm trên THB Vietnam</div>")
                
                # Verify URL matches product
                is_valid, reason = self._verify_url_matches_product(url)
                if is_valid == False:
                    self.thbvietnam_url = False  # Clear wrong URL
                    self.crawled_specs += f"<div style='background: #f8d7da; border: 1px solid #f5c6cb; padding: 10px; margin: 10px 0; color: #721c24;'>❌ <b>URL rejected & cleared:</b> {reason}</div>"
                    _logger.warning(f"[THB Vietnam] URL verification failed: {reason}")
                    return
            else:
                self.crawled_specs = self.crawled_specs.replace(msg_searching,
                    f"<div style='color: #fd7e14;'>⚠ <b>THB Vietnam:</b> {error or 'Không tìm thấy sản phẩm'}</div>")
                _logger.warning(f"[THB Vietnam] Product not found")
                return
        
        if url:
            _logger.info(f"[THB Vietnam] Parsing details from: {url}")
            specs, error = CrawlerUtils.parse_thbvietnam_details(url)
            _logger.info(f"[THB Vietnam] Parse result - Specs length: {len(specs) if specs else 0}, Error: {error}")
            
            if specs:
                self.crawled_specs = (self.crawled_specs or "") + f"<h3 style='color: #007bff;'>📦 THB Vietnam</h3><p style='font-size: 0.85em; color: #6c757d;'>{url}</p>" + specs
            else:
                msg = f"<div style='color: #fd7e14;'>⚠ <b>THB Vietnam:</b> {error or 'Lỗi tải dữ liệu'}</div>"
                self.crawled_specs = (self.crawled_specs or "") + msg
        
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
            self.crawled_specs = (self.crawled_specs or "") + msg_searching
            
            _logger.info(f"[Mecsu] Searching for SKU: {self.default_code}, Name: {self.name}")
            url, error = CrawlerUtils.search_mecsu(self.default_code, self.name)
            _logger.info(f"[Mecsu] Search result - URL: {url}, Error: {error}")
            
            if url:
                self.mecsu_url = url
                self.crawled_specs = self.crawled_specs.replace(msg_searching,
                    f"<div style='color: #28a745; font-size: 0.9em;'>✓ Tìm thấy sản phẩm trên Mecsu.vn</div>")
                
                # Verify URL matches product
                is_valid, reason = self._verify_url_matches_product(url)
                if is_valid == False:
                    self.mecsu_url = False  # Clear wrong URL
                    self.crawled_specs += f"<div style='background: #f8d7da; border: 1px solid #f5c6cb; padding: 10px; margin: 10px 0; color: #721c24;'>❌ <b>URL rejected & cleared:</b> {reason}</div>"
                    _logger.warning(f"[Mecsu] URL verification failed: {reason}")
                    return
            else:
                self.crawled_specs = self.crawled_specs.replace(msg_searching,
                    f"<div style='color: #fd7e14;'>⚠ <b>Mecsu.vn:</b> {error or 'Không tìm thấy sản phẩm'}</div>")
                _logger.warning(f"[Mecsu] Product not found")
                return
        
        if url:
            _logger.info(f"[Mecsu] Parsing details from: {url}")
            specs, error = CrawlerUtils.parse_mecsu_details(url)
            _logger.info(f"[Mecsu] Parse result - Specs length: {len(specs) if specs else 0}, Error: {error}")
            
            if specs:
                self.crawled_specs = (self.crawled_specs or "") + f"<h3 style='color: #007bff;'>📦 Mecsu.vn</h3><p style='font-size: 0.85em; color: #6c757d;'>{url}</p>" + specs
            else:
                msg = f"<div style='color: #fd7e14;'>⚠ <b>Mecsu.vn:</b> {error or 'Lỗi tải dữ liệu'}</div>"
                self.crawled_specs = (self.crawled_specs or "") + msg
        
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
            self.crawled_specs = (self.crawled_specs or "") + msg_searching
            
            _logger.info(f"[Milwaukee] Searching for SKU: {self.default_code}, Name: {self.name}")
            url, error = CrawlerUtils.search_milwaukee(self.default_code, self.name)
            _logger.info(f"[Milwaukee] Search result - URL: {url}, Error: {error}")
            
            if url:
                self.milwaukee_url = url
                self.crawled_specs = self.crawled_specs.replace(msg_searching,
                    f"<div style='color: #28a745; font-size: 0.9em;'>✓ Tìm thấy sản phẩm trên Milwaukee</div>")
                
                # Verify URL matches product
                is_valid, reason = self._verify_url_matches_product(url)
                if is_valid == False:
                    self.milwaukee_url = False  # Clear wrong URL
                    self.crawled_specs += f"<div style='background: #f8d7da; border: 1px solid #f5c6cb; padding: 10px; margin: 10px 0; color: #721c24;'>❌ <b>URL rejected & cleared:</b> {reason}</div>"
                    _logger.warning(f"[Milwaukee] URL verification failed: {reason}")
                    return
            else:
                self.crawled_specs = self.crawled_specs.replace(msg_searching,
                    f"<div style='color: #fd7e14;'>⚠ <b>Milwaukee:</b> {error or 'Không tìm thấy sản phẩm'}</div>")
                _logger.warning(f"[Milwaukee] Product not found")
                return
        
        if url:
            _logger.info(f"[Milwaukee] Parsing details from: {url}")
            specs, error = CrawlerUtils.parse_milwaukee_details(url)
            _logger.info(f"[Milwaukee] Parse result - Specs length: {len(specs) if specs else 0}, Error: {error}")
            
            if specs:
                # Specs already formatted
                self.crawled_specs = (self.crawled_specs or "") + specs
            else:
                msg = f"<div style='color: #fd7e14;'>⚠ <b>Milwaukee:</b> {error or 'Lỗi tải dữ liệu'}</div>"
                self.crawled_specs = (self.crawled_specs or "") + msg
        
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
            self.crawled_specs = (self.crawled_specs or "") + msg_searching
            
            _logger.info(f"[Bosch] Searching for SKU: {self.default_code}, Name: {self.name}")
            url, error = CrawlerUtils.search_bosch(self.default_code, self.name)
            _logger.info(f"[Bosch] Search result - URL: {url}, Error: {error}")
            
            if url:
                self.bosch_url = url
                self.crawled_specs = self.crawled_specs.replace(msg_searching,
                    f"<div style='color: #28a745; font-size: 0.9em;'>✓ Tìm thấy sản phẩm trên Bosch</div>")
                
                # Verify URL matches product
                is_valid, reason = self._verify_url_matches_product(url)
                if is_valid == False:
                    self.bosch_url = False  # Clear wrong URL
                    self.crawled_specs += f"<div style='background: #f8d7da; border: 1px solid #f5c6cb; padding: 10px; margin: 10px 0; color: #721c24;'>❌ <b>URL rejected & cleared:</b> {reason}</div>"
                    _logger.warning(f"[Bosch] URL verification failed: {reason}")
                    return
            else:
                self.crawled_specs = self.crawled_specs.replace(msg_searching,
                    f"<div style='color: #fd7e14;'>⚠ <b>Bosch:</b> {error or 'Không tìm thấy sản phẩm'}</div>")
                _logger.warning(f"[Bosch] Product not found")
                return
        
        if url:
            _logger.info(f"[Bosch] Parsing details from: {url}")
            specs, error = CrawlerUtils.parse_bosch_details(url)
            _logger.info(f"[Bosch] Parse result - Specs length: {len(specs) if specs else 0}, Error: {error}")
            
            if specs:
                self.crawled_specs = (self.crawled_specs or "") + specs
            else:
                msg = f"<div style='color: #fd7e14;'>⚠ <b>Bosch:</b> {error or 'Lỗi tải dữ liệu'}</div>"
                self.crawled_specs = (self.crawled_specs or "") + msg
        
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
                record.crawled_specs = """
                    <div style='background: #fff3cd; padding: 15px; border-radius: 5px; border-left: 4px solid #ffc107;'>
                        <h3 style='color: #856404; margin: 0 0 10px 0;'>⚠️ Không thể tìm kiếm</h3>
                        <p style='margin: 0; color: #856404;'>Sản phẩm chưa có <b>Mã nội bộ (Internal Reference)</b>.</p>
                        <p style='margin: 5px 0 0 0; color: #856404;'>Vui lòng thêm mã sản phẩm trước khi crawl.</p>
                    </div>
                """
                _logger.warning(f"Product {record.name} has no default_code, skipping crawl")
                continue
            
            # Clear previous specs and add header
            record.crawled_specs = f"""
                <div style='background: #f8f9fa; padding: 15px; border-radius: 5px; margin-bottom: 15px;'>
                    <h2 style='color: #495057; margin: 0 0 10px 0;'>🔍 Kết quả tìm kiếm</h2>
                    <p style='margin: 0; color: #6c757d;'>Mã sản phẩm: <b>{record.default_code}</b></p>
                    <p style='margin: 5px 0 0 0; color: #6c757d; font-size: 0.9em;'>Đang tìm kiếm trên 6 trang web...</p>
                </div>
            """
            
            # 1. Official Sites (First Priority)
            try:
                _logger.info("Crawling Milwaukee...")
                record.action_crawl_milwaukee()
            except Exception as e:
                _logger.error(f"Error crawling Milwaukee: {e}")
                record.crawled_specs += f"<div style='color: red;'>Lỗi Milwaukee: {str(e)}</div>"

            try:
                _logger.info("Crawling Bosch...")
                record.action_crawl_bosch()
            except Exception as e:
                _logger.error(f"Error crawling Bosch: {e}")
                record.crawled_specs += f"<div style='color: red;'>Lỗi Bosch: {str(e)}</div>"

            # 2. Reseller Sites
            try:
                _logger.info("Crawling Ketnoitieudung...")
                record.action_crawl_ketnoitieudung()
            except Exception as e:
                _logger.error(f"Error crawling Ketnoitieudung: {e}")
                record.crawled_specs += f"<div style='color: red;'>Lỗi Ketnoitieudung: {str(e)}</div>"
            
            try:
                _logger.info("Crawling Visior...")
                record.action_crawl_visior()
            except Exception as e:
                _logger.error(f"Error crawling Visior: {e}")
                record.crawled_specs += f"<div style='color: red;'>Lỗi Visior: {str(e)}</div>"
            
            try:
                _logger.info("Crawling THB Vietnam...")
                record.action_crawl_thbvietnam()
            except Exception as e:
                _logger.error(f"Error crawling THB Vietnam: {e}")
                record.crawled_specs += f"<div style='color: red;'>Lỗi THB: {str(e)}</div>"
            
            try:
                _logger.info("Crawling Mecsu...")
                record.action_crawl_mecsu()
            except Exception as e:
                _logger.error(f"Error crawling Mecsu: {e}")
                record.crawled_specs += f"<div style='color: red;'>Lỗi Mecsu: {str(e)}</div>"
            
            _logger.info(f"=== Finished crawl for product: {record.name} ===")
