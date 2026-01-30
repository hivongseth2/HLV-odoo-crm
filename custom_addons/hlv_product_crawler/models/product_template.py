from odoo import models, fields, api, _
from odoo.exceptions import UserError
from .crawler_parsers import CrawlerUtils

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    ketnoitieudung_url = fields.Char(string="Ketnoitieudung URL", help="URL to crawl technical specs from ketnoitieudung.vn")
    visior_url = fields.Char(string="Visior URL", help="URL to crawl technical specs from visior.vn")
    thbvietnam_url = fields.Char(string="THB Vietnam URL", help="URL to crawl technical specs from thbvietnam.com")
    mecsu_url = fields.Char(string="Mecsu URL", help="URL to crawl technical specs from mecsu.vn")
    
    crawled_specs = fields.Html(string="Crawled Specifications", sanitize=False)

    def action_crawl_ketnoitieudung(self):
        self.ensure_one()
        url = self.ketnoitieudung_url
        if not url and self.default_code:
            msg_searching = f"<div style='color: #6c757d; font-size: 0.9em;'>🔍 Đang tìm kiếm <b>{self.default_code}</b> trên Ketnoitieudung.vn...</div>"
            self.crawled_specs = (self.crawled_specs or "") + msg_searching
            
            url, error = CrawlerUtils.search_ketnoitieudung(self.default_code)
            if url:
                self.ketnoitieudung_url = url
                # Update the searching message with success
                self.crawled_specs = self.crawled_specs.replace(msg_searching, 
                    f"<div style='color: #28a745; font-size: 0.9em;'>✓ Tìm thấy sản phẩm trên Ketnoitieudung.vn</div>")
            else:
                # Update with failure message
                self.crawled_specs = self.crawled_specs.replace(msg_searching,
                    f"<div style='color: #fd7e14;'>⚠ <b>Ketnoitieudung.vn:</b> {error or 'Không tìm thấy sản phẩm'}</div>")
                return
        
        if url:
            specs, error = CrawlerUtils.parse_ketnoitieudung_details(url)
            if specs:
                self.crawled_specs = (self.crawled_specs or "") + f"<h3 style='color: #007bff;'>📦 Ketnoitieudung.vn</h3><p style='font-size: 0.85em; color: #6c757d;'>{url}</p>" + specs
            else:
                msg = f"<div style='color: #fd7e14;'>⚠ <b>Ketnoitieudung.vn:</b> {error or 'Lỗi tải dữ liệu'}</div>"
                self.crawled_specs = (self.crawled_specs or "") + msg

    def action_crawl_visior(self):
        self.ensure_one()
        url = self.visior_url
        if not url and self.default_code:
            msg_searching = f"<div style='color: #6c757d; font-size: 0.9em;'>🔍 Đang tìm kiếm <b>{self.default_code}</b> trên Visior.vn...</div>"
            self.crawled_specs = (self.crawled_specs or "") + msg_searching
            
            url, error = CrawlerUtils.search_visior(self.default_code)
            if url:
                self.visior_url = url
                self.crawled_specs = self.crawled_specs.replace(msg_searching,
                    f"<div style='color: #28a745; font-size: 0.9em;'>✓ Tìm thấy sản phẩm trên Visior.vn</div>")
            else:
                self.crawled_specs = self.crawled_specs.replace(msg_searching,
                    f"<div style='color: #fd7e14;'>⚠ <b>Visior.vn:</b> {error or 'Không tìm thấy sản phẩm'}</div>")
                return
        
        if url:
            specs, error = CrawlerUtils.parse_visior_details(url)
            if specs:
                self.crawled_specs = (self.crawled_specs or "") + f"<h3 style='color: #007bff;'>📦 Visior.vn</h3><p style='font-size: 0.85em; color: #6c757d;'>{url}</p>" + specs
            else:
                msg = f"<div style='color: #fd7e14;'>⚠ <b>Visior.vn:</b> {error or 'Lỗi tải dữ liệu'}</div>"
                self.crawled_specs = (self.crawled_specs or "") + msg

    def action_crawl_thbvietnam(self):
        self.ensure_one()
        url = self.thbvietnam_url
        if not url and self.default_code:
            msg_searching = f"<div style='color: #6c757d; font-size: 0.9em;'>🔍 Đang tìm kiếm <b>{self.default_code}</b> trên THB Vietnam...</div>"
            self.crawled_specs = (self.crawled_specs or "") + msg_searching
            
            url, error = CrawlerUtils.search_thbvietnam(self.default_code)
            if url:
                self.thbvietnam_url = url
                self.crawled_specs = self.crawled_specs.replace(msg_searching,
                    f"<div style='color: #28a745; font-size: 0.9em;'>✓ Tìm thấy sản phẩm trên THB Vietnam</div>")
            else:
                self.crawled_specs = self.crawled_specs.replace(msg_searching,
                    f"<div style='color: #fd7e14;'>⚠ <b>THB Vietnam:</b> {error or 'Không tìm thấy sản phẩm'}</div>")
                return
        
        if url:
            specs, error = CrawlerUtils.parse_thbvietnam_details(url)
            if specs:
                self.crawled_specs = (self.crawled_specs or "") + f"<h3 style='color: #007bff;'>📦 THB Vietnam</h3><p style='font-size: 0.85em; color: #6c757d;'>{url}</p>" + specs
            else:
                msg = f"<div style='color: #fd7e14;'>⚠ <b>THB Vietnam:</b> {error or 'Lỗi tải dữ liệu'}</div>"
                self.crawled_specs = (self.crawled_specs or "") + msg

    def action_crawl_mecsu(self):
        self.ensure_one()
        url = self.mecsu_url
        if not url and self.default_code:
            msg_searching = f"<div style='color: #6c757d; font-size: 0.9em;'>🔍 Đang tìm kiếm <b>{self.default_code}</b> trên Mecsu.vn...</div>"
            self.crawled_specs = (self.crawled_specs or "") + msg_searching
            
            url, error = CrawlerUtils.search_mecsu(self.default_code)
            if url:
                self.mecsu_url = url
                self.crawled_specs = self.crawled_specs.replace(msg_searching,
                    f"<div style='color: #28a745; font-size: 0.9em;'>✓ Tìm thấy sản phẩm trên Mecsu.vn</div>")
            else:
                self.crawled_specs = self.crawled_specs.replace(msg_searching,
                    f"<div style='color: #fd7e14;'>⚠ <b>Mecsu.vn:</b> {error or 'Không tìm thấy sản phẩm'}</div>")
                return
        
        if url:
            specs, error = CrawlerUtils.parse_mecsu_details(url)
            if specs:
                self.crawled_specs = (self.crawled_specs or "") + f"<h3 style='color: #007bff;'>📦 Mecsu.vn</h3><p style='font-size: 0.85em; color: #6c757d;'>{url}</p>" + specs
            else:
                msg = f"<div style='color: #fd7e14;'>⚠ <b>Mecsu.vn:</b> {error or 'Lỗi tải dữ liệu'}</div>"
                self.crawled_specs = (self.crawled_specs or "") + msg

    def action_crawl_all(self):
        for record in self:
            # Clear previous specs and add header
            record.crawled_specs = f"""
                <div style='background: #f8f9fa; padding: 15px; border-radius: 5px; margin-bottom: 15px;'>
                    <h2 style='color: #495057; margin: 0 0 10px 0;'>🔍 Kết quả tìm kiếm</h2>
                    <p style='margin: 0; color: #6c757d;'>Mã sản phẩm: <b>{record.default_code or 'Chưa có mã'}</b></p>
                    <p style='margin: 5px 0 0 0; color: #6c757d; font-size: 0.9em;'>Đang tìm kiếm trên 4 trang web...</p>
                </div>
            """
            
            # Try all sites - no exceptions, just log results
            record.action_crawl_ketnoitieudung()
            record.action_crawl_visior()
            record.action_crawl_thbvietnam()
            record.action_crawl_mecsu()
