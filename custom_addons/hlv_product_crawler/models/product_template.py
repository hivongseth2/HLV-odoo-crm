from odoo import models, fields, api, _
from odoo.exceptions import UserError
from .crawler_parsers import CrawlerUtils

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    ketnoitieudung_url = fields.Char(string="Ketnoitieudung URL", help="URL to crawl technical specs from ketnoitieudung.vn")
    visior_url = fields.Char(string="Visior URL", help="URL to crawl technical specs from visior.vn")
    thbvietnam_url = fields.Char(string="THB Vietnam URL", help="URL to crawl technical specs from thbvietnam.com")
    mecsu_url = fields.Char(string="Mecsu URL", help="URL to crawl technical specs from mecsu.vn")
    
    crawled_specs = fields.Html(string="Crawled Specifications", sanitize=False, sanitize_attributes=False, sanitize_tags=False, strip_style=False)

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
                    <p style='margin: 5px 0 0 0; color: #6c757d; font-size: 0.9em;'>Đang tìm kiếm trên 4 trang web...</p>
                </div>
            """
            
            # Try all sites - no exceptions, just log results
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
