import requests
from bs4 import BeautifulSoup
import logging
import urllib.parse

_logger = logging.getLogger(__name__)

class CrawlerUtils:
    USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    
    @staticmethod
    def fetch_url(url):
        headers = {'User-Agent': CrawlerUtils.USER_AGENT}
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            return response.text
        except Exception as e:
            _logger.error(f"Error fetching {url}: {e}")
            return None

    @staticmethod
    def search_ketnoitieudung(sku):
        base_url = "https://www.ketnoitieudung.vn"
        search_url = f"{base_url}/tim-kiem?q={urllib.parse.quote(sku)}"
        html = CrawlerUtils.fetch_url(search_url)
        if not html:
            return None
        
        soup = BeautifulSoup(html, 'html.parser')
        # Logic to extract the first product link from search results
        # This selector needs to be verified based on actual site structure
        product_item = soup.select_one('.product-item a') 
        if product_item:
            href = product_item.get('href')
            if href:
                if not href.startswith('http'):
                    return f"{base_url}{href}"
                return href
        return None

    @staticmethod
    def parse_ketnoitieudung_details(url):
        html = CrawlerUtils.fetch_url(url)
        if not html:
            return None
        soup = BeautifulSoup(html, 'html.parser')
        
        # Try to find technical specs
        # Common selectors: #thong-so-ky-thuat, .specs-table, etc.
        # Adjusted based on common patterns, may need refinement
        specs_div = soup.select_one('#thong-so-ky-thuat') or soup.select_one('.tbl-technical')
        
        if specs_div:
            return str(specs_div)
        return "Cannot find specific technical specifications section."

    @staticmethod
    def search_visior(sku):
        base_url = "https://visior.vn"
        search_url = f"{base_url}/tim-kiem?q={urllib.parse.quote(sku)}"
        html = CrawlerUtils.fetch_url(search_url)
        if not html:
            return None
        
        soup = BeautifulSoup(html, 'html.parser')
        product_item = soup.select_one('.product-block .name a')
        if product_item:
             href = product_item.get('href')
             if href:
                if not href.startswith('http'):
                    return f"{base_url}{href}"
                return href
        return None

    @staticmethod
    def parse_visior_details(url):
        html = CrawlerUtils.fetch_url(url)
        if not html:
            return None
        soup = BeautifulSoup(html, 'html.parser')
        
        # Visior specs usually in a table or div
        specs_div = soup.select_one('#thong-so-ky-thuat') or soup.find('div', string='Thông số kỹ thuật')
        # If finding by string ID fails, try simpler container
        if not specs_div:
            # Fallback to description content if specific spec div missing
             specs_div = soup.select_one('.product-desc') 
             
        if specs_div:
            return str(specs_div)
        return "Cannot find specific technical specifications section."

    @staticmethod
    def search_thbvietnam(sku):
        base_url = "https://thbvietnam.com"
        search_url = f"{base_url}/catalogsearch/result/?q={urllib.parse.quote(sku)}"
        html = CrawlerUtils.fetch_url(search_url)
        if not html:
            return None
            
        soup = BeautifulSoup(html, 'html.parser')
        product_item = soup.select_one('.product-item-link')
        if product_item:
            href = product_item.get('href')
            if href:
                return href
        return None

    @staticmethod
    def parse_thbvietnam_details(url):
        html = CrawlerUtils.fetch_url(url)
        if not html:
            return None
        soup = BeautifulSoup(html, 'html.parser')
        
        # THB usually uses a table in 'additional-attributes'
        specs_table = soup.select_one('#product-attribute-specs-table')
        if specs_table:
            return str(specs_table)
            
        return "Cannot find specific technical specifications section."
