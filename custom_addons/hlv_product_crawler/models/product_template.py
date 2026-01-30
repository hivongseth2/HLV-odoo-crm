from odoo import models, fields, api, _
from odoo.exceptions import UserError
from .crawler_parsers import CrawlerUtils

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    ketnoitieudung_url = fields.Char(string="Ketnoitieudung URL", help="URL to crawl technical specs from ketnoitieudung.vn")
    visior_url = fields.Char(string="Visior URL", help="URL to crawl technical specs from visior.vn")
    thbvietnam_url = fields.Char(string="THB Vietnam URL", help="URL to crawl technical specs from thbvietnam.com")
    
    crawled_specs = fields.Html(string="Crawled Specifications", sanitize=False)

    def action_crawl_ketnoitieudung(self):
        self.ensure_one()
        url = self.ketnoitieudung_url
        if not url and self.default_code:
            url, error = CrawlerUtils.search_ketnoitieudung(self.default_code)
            if url:
                self.ketnoitieudung_url = url
            else:
                # Don't raise error, just append message
                msg = f"<div style='color: orange;'><b>Ketnoitieudung.vn:</b> {error or 'Không tìm thấy sản phẩm'}</div>"
                self.crawled_specs = (self.crawled_specs or "") + msg
                return
        
        if url:
            specs, error = CrawlerUtils.parse_ketnoitieudung_details(url)
            if specs:
                self.crawled_specs = (self.crawled_specs or "") + f"<h3>Ketnoitieudung ({url})</h3>" + specs
            else:
                msg = f"<div style='color: orange;'><b>Ketnoitieudung.vn:</b> {error or 'Lỗi tải dữ liệu'}</div>"
                self.crawled_specs = (self.crawled_specs or "") + msg

    def action_crawl_visior(self):
        self.ensure_one()
        url = self.visior_url
        if not url and self.default_code:
            url, error = CrawlerUtils.search_visior(self.default_code)
            if url:
                self.visior_url = url
            else:
                msg = f"<div style='color: orange;'><b>Visior.vn:</b> {error or 'Không tìm thấy sản phẩm'}</div>"
                self.crawled_specs = (self.crawled_specs or "") + msg
                return
        
        if url:
            specs, error = CrawlerUtils.parse_visior_details(url)
            if specs:
                self.crawled_specs = (self.crawled_specs or "") + f"<h3>Visior ({url})</h3>" + specs
            else:
                msg = f"<div style='color: orange;'><b>Visior.vn:</b> {error or 'Lỗi tải dữ liệu'}</div>"
                self.crawled_specs = (self.crawled_specs or "") + msg

    def action_crawl_thbvietnam(self):
        self.ensure_one()
        url = self.thbvietnam_url
        if not url and self.default_code:
            url, error = CrawlerUtils.search_thbvietnam(self.default_code)
            if url:
                self.thbvietnam_url = url
            else:
                msg = f"<div style='color: orange;'><b>THB Vietnam:</b> {error or 'Không tìm thấy sản phẩm'}</div>"
                self.crawled_specs = (self.crawled_specs or "") + msg
                return
        
        if url:
            specs, error = CrawlerUtils.parse_thbvietnam_details(url)
            if specs:
                self.crawled_specs = (self.crawled_specs or "") + f"<h3>THB Vietnam ({url})</h3>" + specs
            else:
                msg = f"<div style='color: orange;'><b>THB Vietnam:</b> {error or 'Lỗi tải dữ liệu'}</div>"
                self.crawled_specs = (self.crawled_specs or "") + msg

    def action_crawl_all(self):
        for record in self:
            # Clear previous specs for fresh crawl
            record.crawled_specs = ""
            
            # Try all sites - no exceptions, just log results
            record.action_crawl_ketnoitieudung()
            record.action_crawl_visior()
            record.action_crawl_thbvietnam()
