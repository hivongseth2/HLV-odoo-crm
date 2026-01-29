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
            url = CrawlerUtils.search_ketnoitieudung(self.default_code)
            if url:
                self.ketnoitieudung_url = url
            else:
                raise UserError(_("Could not find product on Ketnoitieudung with code %s") % self.default_code)
        
        if url:
            specs = CrawlerUtils.parse_ketnoitieudung_details(url)
            if specs:
                self.crawled_specs = (self.crawled_specs or "") + f"<h3>Ketnoitieudung ({url})</h3>" + specs

    def action_crawl_visior(self):
        self.ensure_one()
        url = self.visior_url
        if not url and self.default_code:
            url = CrawlerUtils.search_visior(self.default_code)
            if url:
                self.visior_url = url
            else:
                raise UserError(_("Could not find product on Visior with code %s") % self.default_code)
        
        if url:
            specs = CrawlerUtils.parse_visior_details(url)
            if specs:
                self.crawled_specs = (self.crawled_specs or "") + f"<h3>Visior ({url})</h3>" + specs

    def action_crawl_thbvietnam(self):
        self.ensure_one()
        url = self.thbvietnam_url
        if not url and self.default_code:
            url = CrawlerUtils.search_thbvietnam(self.default_code)
            if url:
                self.thbvietnam_url = url
            else:
                 raise UserError(_("Could not find product on THB Vietnam with code %s") % self.default_code)
        
        if url:
            specs = CrawlerUtils.parse_thbvietnam_details(url)
            if specs:
                self.crawled_specs = (self.crawled_specs or "") + f"<h3>THB Vietnam ({url})</h3>" + specs

    def action_crawl_all(self):
        for record in self:
            # Clear previous specs to avoid duplication when crawling all again? 
            # Or just append? Let's clear for fresh crawl.
            record.crawled_specs = ""
            try:
                record.action_crawl_ketnoitieudung()
            except UserError:
                pass
            try:
                record.action_crawl_visior()
            except UserError:
                pass
            try:
                record.action_crawl_thbvietnam()
            except UserError:
                pass
