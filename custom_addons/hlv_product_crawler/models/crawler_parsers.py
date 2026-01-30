import requests
from bs4 import BeautifulSoup
import logging
import urllib.parse

_logger = logging.getLogger(__name__)

class CrawlerUtils:
    USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    
    @staticmethod
    def fetch_url(url):
        """Fetch URL and return (html_content, error_message) tuple"""
        headers = {'User-Agent': CrawlerUtils.USER_AGENT}
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            return response.text, None
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                _logger.info(f"Page not found (404): {url}")
                return None, "404 - Trang không tồn tại"
            else:
                _logger.warning(f"HTTP error {e.response.status_code} fetching {url}")
                return None, f"HTTP {e.response.status_code}"
        except requests.exceptions.Timeout:
            _logger.warning(f"Timeout fetching {url}")
            return None, "Timeout - Hết thời gian chờ"
        except requests.exceptions.ConnectionError:
            _logger.warning(f"Connection error fetching {url}")
            return None, "Lỗi kết nối"
        except Exception as e:
            _logger.error(f"Unexpected error fetching {url}: {e}")
            return None, f"Lỗi: {str(e)}"

    @staticmethod
    def search_ketnoitieudung(sku):
        """Search for product and return (url, error_message) tuple"""
        base_url = "https://www.ketnoitieudung.vn"
        
        # Try multiple query variations for better matching
        queries = [
            sku,
            sku.replace('-', '').replace(' ', ''),
            sku.upper(),
            sku.lower(),
        ]
        
        for query in queries:
            search_url = f"{base_url}/tim-kiem?q={urllib.parse.quote(query)}"
            html, error = CrawlerUtils.fetch_url(search_url)
            if not html:
                continue
        
            soup = BeautifulSoup(html, 'html.parser')
            product_item = (soup.select_one('.product-item a') or
                           soup.select_one('a[href*="/san-pham/"]'))
            if product_item:
                href = product_item.get('href')
                if href:
                    if not href.startswith('http'):
                        return f"{base_url}{href}", None
                    return href, None
        
        return None, "Không tìm thấy sản phẩm (đã thử nhiều biến thể)"

    @staticmethod
    def parse_ketnoitieudung_details(url):
        """Parse product details and return (specs_html, error_message) tuple"""
        html, error = CrawlerUtils.fetch_url(url)
        if not html:
            return None, error or "Lỗi tải trang"
        soup = BeautifulSoup(html, 'html.parser')
        
        specs_div = soup.select_one('#thong-so-ky-thuat') or soup.select_one('.tbl-technical')
        
        if specs_div:
            return str(specs_div), None
        return None, "Không tìm thấy thông số kỹ thuật"

    @staticmethod
    def search_visior(sku):
        """Search for product and return (url, error_message) tuple"""
        base_url = "https://visior.vn"
        
        # Try multiple query variations for better matching
        queries = [
            sku,  # Original
            sku.replace('-', '').replace(' ', ''),  # No dashes/spaces: 48228301
            sku.upper(),  # Uppercase
            sku.lower(),  # Lowercase
        ]
        
        for query in queries:
            # CORRECTED: Use /search instead of /tim-kiem
            search_url = f"{base_url}/search?q={urllib.parse.quote(query)}"
            html, error = CrawlerUtils.fetch_url(search_url)
            if not html:
                continue  # Try next variation
            
            soup = BeautifulSoup(html, 'html.parser')
            # Try multiple selectors
            product_item = (soup.select_one('.product-block .name a') or 
                           soup.select_one('.product-item a') or
                           soup.select_one('a[href*="/san-pham/"]'))
            if product_item:
                 href = product_item.get('href')
                 if href:
                    if not href.startswith('http'):
                        return f"{base_url}{href}", None
                    return href, None
        
        return None, "Không tìm thấy sản phẩm (đã thử nhiều biến thể)"

    @staticmethod
    def parse_visior_details(url):
        """Parse product details and return (specs_html, error_message) tuple"""
        html, error = CrawlerUtils.fetch_url(url)
        if not html:
            return None, error or "Lỗi tải trang"
        soup = BeautifulSoup(html, 'html.parser')
        
        specs_div = soup.select_one('#thong-so-ky-thuat') or soup.find('div', string='Thông số kỹ thuật')
        if not specs_div:
             specs_div = soup.select_one('.product-desc') 
             
        if specs_div:
            return str(specs_div), None
        return None, "Không tìm thấy thông số kỹ thuật"

    @staticmethod
    def search_thbvietnam(sku):
        """Search for product and return (url, error_message) tuple"""
        base_url = "https://thbvietnam.com"
        
        # Try multiple query variations
        queries = [
            sku,
            sku.replace('-', '').replace(' ', ''),
            sku.upper(),
            sku.lower(),
        ]
        
        for query in queries:
            # CORRECTED: Use /tim-kiem instead of /catalogsearch/result/
            search_url = f"{base_url}/tim-kiem?q={urllib.parse.quote(query)}"
            html, error = CrawlerUtils.fetch_url(search_url)
            if not html:
                continue
                
            soup = BeautifulSoup(html, 'html.parser')
            # Try multiple selectors
            product_item = (soup.select_one('.product-item-link') or
                           soup.select_one('.product-item a') or
                           soup.select_one('a[href*="/san-pham/"]'))
            if product_item:
                href = product_item.get('href')
                if href:
                    return href, None
        
        return None, "Không tìm thấy sản phẩm (đã thử nhiều biến thể)"

    @staticmethod
    def parse_thbvietnam_details(url):
        """Parse product details and return (specs_html, error_message) tuple"""
        html, error = CrawlerUtils.fetch_url(url)
        if not html:
            return None, error or "Lỗi tải trang"
        soup = BeautifulSoup(html, 'html.parser')
        
        specs_table = soup.select_one('#product-attribute-specs-table')
        if specs_table:
            return str(specs_table), None
            
        return None, "Không tìm thấy thông số kỹ thuật"
