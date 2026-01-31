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
    def extract_keywords(product_name):
        """Extract search keywords from product name"""
        import re
        if not product_name:
            return []
        
        keywords = []
        # Extract brand (uppercase words with 2+ chars)
        brands = re.findall(r'\b[A-Z]{2,}[A-Z0-9]*\b', product_name)
        keywords.extend(brands)
        
        # Extract model numbers (alphanumeric with dashes)
        models = re.findall(r'\b[A-Z0-9]+-[A-Z0-9-]+\b', product_name)
        keywords.extend(models)
        
        # Get first 2-3 meaningful words (3+ chars)
        words = re.findall(r'\b\w{3,}\b', product_name)
        keywords.extend(words[:3])
        
        # Remove duplicates while preserving order
        return list(dict.fromkeys(keywords))
    
    @staticmethod
    def format_specs_table(soup_table, site_name, site_color="#007bff"):
        """Format specs table into beautiful HTML"""
        if not soup_table:
            return ""
        
        rows = soup_table.find_all('tr')
        if not rows:
            return ""
        
        html = f"""
        <div style='background: #fff; border: 1px solid #e0e0e0; border-radius: 8px; padding: 20px; margin: 15px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1);'>
            <div style='border-bottom: 3px solid {site_color}; padding-bottom: 10px; margin-bottom: 15px;'>
                <h3 style='color: {site_color}; margin: 0; font-size: 18px; font-weight: 600;'>📦 {site_name}</h3>
            </div>
            <table style='width: 100%; border-collapse: collapse;'>
        """
        
        for i, row in enumerate(rows):
            cols = row.find_all('td')
            if len(cols) >= 2:
                label = cols[0].get_text(strip=True)
                value = cols[1].get_text(strip=True)
                
                bg_color = '#f8f9fa' if i % 2 == 0 else '#ffffff'
                html += f"""
                <tr style='background: {bg_color};'>
                    <td style='padding: 10px; font-weight: 500; color: #495057; width: 35%; border-bottom: 1px solid #e9ecef;'>{label}</td>
                    <td style='padding: 10px; color: #212529; border-bottom: 1px solid #e9ecef;'>{value}</td>
                </tr>
                """
        
        html += """</table></div>"""
        return html

    @staticmethod
    def search_ketnoitieudung(sku, product_name=None):
        """Search for product and return (url, error_message) tuple"""
        base_url = "https://www.ketnoitieudung.vn"
        
        # Build query variations
        queries = [sku] if sku else []
        
        if sku:
            queries.extend([
                sku.replace('-', '').replace(' ', ''),
                sku.upper(),
                sku.lower(),
            ])
        
        # Add product name variations
        if product_name:
            queries.append(product_name)
            keywords = CrawlerUtils.extract_keywords(product_name)
            if len(keywords) >= 2:
                queries.append(' '.join(keywords[:2]))
            if keywords:
                queries.append(keywords[0])
        
        for query in queries:
            # FIXED: Correct URL is /san-pham.html?keyword= (not /tim-kiem?q=)
            search_url = f"{base_url}/san-pham.html?keyword={urllib.parse.quote(query)}"
            html, error = CrawlerUtils.fetch_url(search_url)
            if not html:
                continue
            
            soup = BeautifulSoup(html, 'html.parser')
            # FIXED: Correct selector is .product-card__name a
            product_item = (soup.select_one('.product-card__name a') or
                           soup.select_one('.product-card a') or
                           soup.select_one('a[href*=".html"]'))
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
        
        # FIXED: Check new selector first, then fall back to old ones
        specs_table = (soup.select_one('#tab-specification table') or
                      soup.select_one('#thong-so-ky-thuat table') or 
                      soup.select_one('.tbl-technical'))
        
        if specs_table:
            # Format into beautiful HTML
            formatted_html = CrawlerUtils.format_specs_table(specs_table, "Ketnoitieudung.vn", "#28a745")
            return formatted_html, None
        return None, "Không tìm thấy thông số kỹ thuật"

    @staticmethod
    def search_visior(sku, product_name=None):
        """Search for product and return (url, error_message) tuple"""
        base_url = "https://visior.vn"
        
        # Build query variations
        queries = [sku] if sku else []
        
        if sku:
            queries.extend([
                sku.replace('-', '').replace(' ', ''),
                sku.upper(),
                sku.lower(),
            ])
        
        # Add product name variations
        if product_name:
            queries.append(product_name)
            keywords = CrawlerUtils.extract_keywords(product_name)
            if len(keywords) >= 2:
                queries.append(' '.join(keywords[:2]))
            if keywords:
                queries.append(keywords[0])
        
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
    def search_thbvietnam(sku, product_name=None):
        """Search for product and return (url, error_message) tuple"""
        base_url = "https://thbvietnam.com"
        
        # Build query variations
        queries = [sku] if sku else []
        
        if sku:
            queries.extend([
                sku.replace('-', '').replace(' ', ''),
                sku.upper(),
                sku.lower(),
            ])
        
        # Add product name variations
        if product_name:
            queries.append(product_name)
            keywords = CrawlerUtils.extract_keywords(product_name)
            if len(keywords) >= 2:
                queries.append(' '.join(keywords[:2]))
            if keywords:
                queries.append(keywords[0])
        
        for query in queries:
            # FIXED: Parameter is 'keywords' not 'q'
            search_url = f"{base_url}/tim-kiem?keywords={urllib.parse.quote(query)}"
            html, error = CrawlerUtils.fetch_url(search_url)
            if not html:
                continue
                
            soup = BeautifulSoup(html, 'html.parser')
            # Try multiple selectors
            product_item = (soup.select_one('.item a') or
                           soup.select_one('.product-item-link') or
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

    @staticmethod
    def search_mecsu(sku, product_name=None):
        """Search for product and return (url, error_message) tuple"""
        base_url = "https://mecsu.vn"
        
        # Build query variations
        queries = [sku] if sku else []
        
        if sku:
            queries.extend([
                sku.replace('-', '').replace(' ', ''),
                sku.upper(),
                sku.lower(),
            ])
        
        # Add product name variations
        if product_name:
            queries.append(product_name)
            keywords = CrawlerUtils.extract_keywords(product_name)
            if len(keywords) >= 2:
                queries.append(' '.join(keywords[:2]))
            if keywords:
                queries.append(keywords[0])
        
        for query in queries:
            # Mecsu uses /site?keyword= pattern
            search_url = f"{base_url}/site?keyword={urllib.parse.quote(query)}"
            html, error = CrawlerUtils.fetch_url(search_url)
            if not html:
                continue
                
            soup = BeautifulSoup(html, 'html.parser')
            
            # FIXED: Mecsu search results use popups, not direct links
            # IMPORTANT: Filter by title="Thông số kỹ thuật" to get specs button (not "Tải bảng giá")
            popup_btn = soup.select_one('a.mecsu-button-popup-lg[title="Thông số kỹ thuật"]')
            if popup_btn:
                # Extract quick-view URL from value attribute
                quick_view_path = popup_btn.get('value')
                if quick_view_path and 'product-quick-view' in quick_view_path:
                    # Step 2: Fetch quick-view page to get actual product link
                    quick_view_url = f"{base_url}{quick_view_path}"
                    quick_html, quick_error = CrawlerUtils.fetch_url(quick_view_url)
                    
                    if quick_html:
                        quick_soup = BeautifulSoup(quick_html, 'html.parser')
                        # Step 3: Find "Xem chi tiết" link in quick-view response
                        detail_links = quick_soup.select('a[href*="/chi-tiet/"]')
                        for link in detail_links:
                            if 'Xem chi tiết' in link.get_text():
                                href = link.get('href')
                                if href:
                                    if not href.startswith('http'):
                                        return f"{base_url}{href}", None
                                    return href, None
        
        return None, "Không tìm thấy sản phẩm (đã thử nhiều biến thể)"

    @staticmethod
    def parse_mecsu_details(url):
        """Parse product details and return (specs_html, error_message) tuple"""
        html, error = CrawlerUtils.fetch_url(url)
        if not html:
            return None, error or "Lỗi tải trang"
        soup = BeautifulSoup(html, 'html.parser')
        
        # Mecsu  has multiple formats
        # 1. Table in #information section
        info_section = soup.select_one('#information')
        if info_section:
            table = info_section.select_one('table')
            if table:
                return str(table), None
        
        # 2. Additional info list (PRIMARY for Mecsu)
        specs_list = soup.select_one('.additional__info_list')
        if specs_list:
            # Extract list items and format beautifully
            items = specs_list.find_all('li')
            if items:
                rows_data = []
                for item in items:
                    label_elem = item.select_one('.info__list--item-head strong') or item.select_one('.info__list--item-head')
                    value_elem = item.select_one('.info__list--item-content')
                    
                    if label_elem and value_elem:
                        label = label_elem.get_text(strip=True)
                        value = value_elem.get_text(strip=True)
                        rows_data.append((label, value))
                
                if rows_data:
                    site_color = "#fd7e14"
                    html_output = f"""
                    <div style='background: #fff; border: 1px solid #e0e0e0; border-radius: 8px; padding: 20px; margin: 15px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1);'>
                        <div style='border-bottom: 3px solid {site_color}; padding-bottom: 10px; margin-bottom: 15px;'>
                            <h3 style='color: {site_color}; margin: 0; font-size: 18px; font-weight: 600;'>📦 Mecsu.vn</h3>
                        </div>
                        <table style='width: 100%; border-collapse: collapse;'>
                    """
                    
                    for i, (label, value) in enumerate(rows_data):
                        bg_color = '#f8f9fa' if i % 2 == 0 else '#ffffff'
                        html_output += f"""
                        <tr style='background: {bg_color};'>
                            <td style='padding: 10px; font-weight: 500; color: #495057; width: 35%; border-bottom: 1px solid #e9ecef;'>{label}</td>
                            <td style='padding: 10px; color: #212529; border-bottom: 1px solid #e9ecef;'>{value}</td>
                        </tr>
                        """
                    
                    html_output += """</table></div>"""
                    return html_output, None
            
        # 3. Product details info table
        details_table = soup.select_one('.product__details--info__table')
        if details_table:
            return str(details_table), None
            
        return None, "Không tìm thấy thông số kỹ thuật"

    @staticmethod
    def search_milwaukee(sku, product_name=None):
        """Search for product on milwaukeetool.com.vn and return (url, error_message) tuple"""
        base_url = "https://www.milwaukeetool.com.vn"
        
        queries = [sku] if sku else []
        if sku:
            queries.extend([
                sku.replace('-', '').replace(' ', ''),
                sku.strip(),
            ])
            
        # Try simplified SKU (e.g. M18 FPD3-0X -> M18 FPD3)
        if sku and '-' in sku:
             parts = sku.split('-')
             if len(parts) > 1:
                 queries.append(parts[0])

        # Try simplified SKU by space (e.g. M18 FPD3 -> M18, FPD3)
        if sku and ' ' in sku:
             parts = sku.split(' ')
             if len(parts) > 0:
                 queries.append(parts[0]) # Start part (M18)
                 if len(parts) > 1 and len(parts[1]) > 2:
                    queries.append(parts[1]) # End part (FPD3)

        for query in queries:
            search_url = f"{base_url}/catalogsearch/result/?q={urllib.parse.quote(query)}"
            html, error = CrawlerUtils.fetch_url(search_url)
            if not html:
                continue
                
            soup = BeautifulSoup(html, 'html.parser')
            
            # Selector: .product-item-photo (link is on image)
            product_link = soup.select_one('.product-item-photo')
            if product_link:
                href = product_link.get('href')
                if href:
                    if not href.startswith('http'):
                        return f"{base_url}{href}", None
                    return href, None
        
        return None, "Không tìm thấy sản phẩm trên Milwaukee"

    @staticmethod
    def parse_milwaukee_details(url):
        """Parse product details from Milwaukee Tool and return (specs_html, error_message) tuple"""
        html, error = CrawlerUtils.fetch_url(url)
        if not html:
            return None, error or "Lỗi tải trang"
        soup = BeautifulSoup(html, 'html.parser')
        
        # Specs are .specification-list rows
        spec_rows = soup.select('.specification-list')
        
        if spec_rows:
            # Manually extract to format nicely
            rows_data = []
            
            for row in spec_rows:
                # Direct children are columns (Label, Value)
                cols = row.find_all('div', recursive=False)
                # Filter out style tags or hidden elements if needed?
                # Based on dump, first col is Label, others are values
                
                valid_cols = []
                for c in cols:
                    # Skip if text is mostly css (contains '{')
                    txt = c.get_text(strip=True)
                    if '{' not in txt and '}' not in txt:
                         valid_cols.append(txt)
                
                if len(valid_cols) >= 2:
                    label = valid_cols[0]
                    # Join rest as value
                    value = " ".join(valid_cols[1:])
                    rows_data.append((label, value))
            
            if rows_data:
                # Custom formatting
                site_color = "#ff0000" # Milwaukee Red
                html_output = f"""
                <div style='background: #fff; border: 1px solid #e0e0e0; border-radius: 8px; padding: 20px; margin: 15px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1);'>
                    <div style='border-bottom: 3px solid {site_color}; padding-bottom: 10px; margin-bottom: 15px;'>
                        <h3 style='color: {site_color}; margin: 0; font-size: 18px; font-weight: 600;'>📦 Milwaukee Tool VN</h3>
                    </div>
                    <table style='width: 100%; border-collapse: collapse;'>
                """
                
                for i, (label, value) in enumerate(rows_data):
                    bg_color = '#f8f9fa' if i % 2 == 0 else '#ffffff'
                    html_output += f"""
                    <tr style='background: {bg_color};'>
                        <td style='padding: 10px; font-weight: 500; color: #495057; width: 35%; border-bottom: 1px solid #e9ecef;'>{label}</td>
                        <td style='padding: 10px; color: #212529; border-bottom: 1px solid #e9ecef;'>{value}</td>
                    </tr>
                    """
                
                html_output += """</table></div>"""
                return html_output, None

        return None, "Không tìm thấy thông số kỹ thuật (Milwaukee)"

    @staticmethod
    def search_bosch(sku, product_name=None):
        """Search for product on vn.bosch-pt.com"""
        base_url = "https://vn.bosch-pt.com"
        
        queries = [sku] if sku else []
        if sku:
            queries.extend([sku.strip()])
            
        for query in queries:
            search_url = f"{base_url}/vn/vi/searchfrontend/?q={urllib.parse.quote(query)}"
            html, error = CrawlerUtils.fetch_url(search_url)
            if not html:
                continue
                
            soup = BeautifulSoup(html, 'html.parser')
            
            # Selector: a.category-grid-tile__link-wrapper
            product_link = soup.select_one('a.category-grid-tile__link-wrapper')
            if product_link:
                href = product_link.get('href')
                if href:
                    if not href.startswith('http'):
                        if href.startswith('/'):
                            return f"{base_url}{href}", None
                        return f"{base_url}/{href}", None
                    return href, None
        
        return None, "Không tìm thấy sản phẩm trên Bosch VN"

    @staticmethod
    def parse_bosch_details(url):
        """Parse specs from Bosch div-based table"""
        html, error = CrawlerUtils.fetch_url(url)
        if not html:
            return None, error or "Lỗi tải trang"
        soup = BeautifulSoup(html, 'html.parser')
        
        # Bosch uses .table__body with .table__body-row and .table__body-cell
        table_body = soup.select_one('.table__body')
        
        rows_data = []
        if table_body:
            rows = table_body.select('.table__body-row')
            for row in rows:
                cells = row.select('.table__body-cell')
                if len(cells) >= 2:
                    label = cells[0].get_text(strip=True)
                    value = cells[1].get_text(strip=True)
                    if label:
                         rows_data.append((label, value))
        
        if rows_data:
            site_color = "#005691" # Bosch Blue (approx)
            html_output = f"""
            <div style='background: #fff; border: 1px solid #e0e0e0; border-radius: 8px; padding: 20px; margin: 15px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1);'>
                <div style='border-bottom: 3px solid {site_color}; padding-bottom: 10px; margin-bottom: 15px;'>
                    <h3 style='color: {site_color}; margin: 0; font-size: 18px; font-weight: 600;'>📦 Bosch Professional VN</h3>
                </div>
                <table style='width: 100%; border-collapse: collapse;'>
            """
            
            for i, (label, value) in enumerate(rows_data):
                 bg_color = '#f8f9fa' if i % 2 == 0 else '#ffffff'
                 html_output += f"""
                 <tr style='background: {bg_color};'>
                     <td style='padding: 10px; font-weight: 500; color: #495057; width: 35%; border-bottom: 1px solid #e9ecef;'>{label}</td>
                     <td style='padding: 10px; color: #212529; border-bottom: 1px solid #e9ecef;'>{value}</td>
                 </tr>
                 """
            
            html_output += """</table></div>"""
            return html_output, None
            
        return None, "Không tìm thấy thông số kỹ thuật (Bosch)"
