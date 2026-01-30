#!/usr/bin/env python3
"""
COMPREHENSIVE LOCAL TEST cho crawler
Test TẤT CẢ search + parse functions TRƯỚC KHI PUSH
"""

import requests
from bs4 import BeautifulSoup
import urllib.parse

def fetch_url(url):
    """Fetch URL with proper headers"""
    try:
        response = requests.get(url, timeout=10, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        if response.status_code == 200:
            return response.content, None
        return None, f"HTTP {response.status_code}"
    except Exception as e:
        return None, str(e)

# ==================== TEST CASE ====================
sku = "M18 FPD3-0"
product_name = "May khoan dong luc M18 FPD3-0 (bare) MILWAUKEE"

print("=" * 80)
print("COMPREHENSIVE CRAWLER TEST")
print("=" * 80)
print(f"\nTest Product: {product_name}")
print(f"SKU: {sku}\n")

# ==================== TEST 1: KETNOITIEUDUNG.VN ====================
print("\n" + "=" * 80)
print("TEST 1: KETNOITIEUDUNG.VN")
print("=" * 80)

# Test search URL
search_url = f"https://www.ketnoitieudung.vn/san-pham.html?keyword={urllib.parse.quote(sku)}"
print(f"\n[SEARCH] URL: {search_url}")

html, error = fetch_url(search_url)
if html:
    soup = BeautifulSoup(html, 'html.parser')
    
    # Test selectors
    selectors = [
        '.product-card__name a',
        '.product-card a',
        'a[href*=".html"]'
    ]
    
    found_url = None
    for selector in selectors:
        product = soup.select_one(selector)
        if product and product.get('href'):
            found_url = product.get('href')
            if not found_url.startswith('http'):
                found_url = f"https://www.ketnoitieudung.vn{found_url}"
            print(f"[SEARCH] SUCCESS with selector: {selector}")
            print(f"[SEARCH] Product URL: {found_url}")
            break
    
    if not found_url:
        print("[SEARCH] FAILED - No product found")
    else:
        # Test parse
        print(f"\n[PARSE] Testing URL: {found_url}")
        detail_html, detail_error = fetch_url(found_url)
        
        if detail_html:
            detail_soup = BeautifulSoup(detail_html, 'html.parser')
            
            # Test parse selectors
            parse_selectors = [
                '#tab-specification table',
                '#thong-so-ky-thuat',
                '.tbl-technical'
            ]
            
            for ps in parse_selectors:
                specs = detail_soup.select_one(ps)
                if specs:
                    print(f"[PARSE] SUCCESS with selector: {ps}")
                    print(f"[PARSE] Specs length: {len(str(specs))} chars")
                    
                    # Show first few rows
                    if ps == '#tab-specification table':
                        rows = specs.find_all('tr')[:3]
                        print("[PARSE] Sample rows:")
                        for row in rows:
                            cols = row.find_all('td')
                            if len(cols) == 2:
                                print(f"  - {cols[0].text.strip()}: {cols[1].text.strip()}")
                    break
            else:
                print("[PARSE] FAILED - No specs found")
        else:
            print(f"[PARSE] FAILED - {detail_error}")
else:
    print(f"[SEARCH] FAILED - {error}")

# ==================== TEST 2: VISIOR.VN ====================
print("\n" + "=" * 80)
print("TEST 2: VISIOR.VN")
print("=" * 80)

search_url = f"https://visior.vn/search?q={urllib.parse.quote(sku)}"
print(f"\n[SEARCH] URL: {search_url}")

html, error = fetch_url(search_url)
if html:
    soup = BeautifulSoup(html, 'html.parser')
    
    selectors = [
        '.product-block .name a',
        '.product-item a',
        'a[href*="/san-pham/"]'
    ]
    
    for selector in selectors:
        product = soup.select_one(selector)
        if product and product.get('href'):
            print(f"[SEARCH] SUCCESS with selector: {selector}")
            print(f"[SEARCH] Product URL: {product.get('href')}")
            break
    else:
        print("[SEARCH] INFO - No product found (may not have this product)")
else:
    print(f"[SEARCH] FAILED - {error}")

# ==================== TEST 3: THB VIETNAM ====================
print("\n" + "=" * 80)
print("TEST 3: THB VIETNAM")
print("=" * 80)

# FIXED URL with 'keywords' parameter
search_url = f"https://thbvietnam.com/tim-kiem?keywords={urllib.parse.quote(sku)}"
print(f"\n[SEARCH] URL: {search_url}")

html, error = fetch_url(search_url)
if html:
    soup = BeautifulSoup(html, 'html.parser')
    
    selectors = [
        '.item a',
        '.product-item-link',
        '.product-item a',
        'a[href*="/san-pham/"]'
    ]
    
    for selector in selectors:
        product = soup.select_one(selector)
        if product and product.get('href'):
            print(f"[SEARCH] SUCCESS with selector: {selector}")
            print(f"[SEARCH] Product URL: {product.get('href')}")
            break
    else:
        print("[SEARCH] INFO - No product found (may not have this product)")
else:
    print(f"[SEARCH] FAILED - {error}")

# ==================== TEST 4: MECSU.VN ====================
print("\n" + "=" * 80)
print("TEST 4: MECSU.VN")
print("=" * 80)

search_url = f"https://mecsu.vn/site?keyword={urllib.parse.quote(sku)}"
print(f"\n[SEARCH] URL: {search_url}")

html, error = fetch_url(search_url)
if html:
    soup = BeautifulSoup(html, 'html.parser')
    
    # Mecsu uses popups - check for popup triggers
    popup_triggers = soup.select('.mecsu-button-popup-lg[value*="product-quick-view"]')
    
    if popup_triggers:
        print(f"[SEARCH] FOUND {len(popup_triggers)} products")
        print(f"[SEARCH] NOTE: Mecsu uses popups - product detail in modal")
        
        # Check first trigger
        first_trigger = popup_triggers[0]
        value = first_trigger.get('value')
        if value:
            print(f"[SEARCH] First product modal path: {value}")
            
            # Try to extract product ID
            if 'id=' in value:
                product_id = value.split('id=')[1]
                print(f"[SEARCH] Product ID: {product_id}")
        
        # Show product name if available
        product_name_elem = first_trigger.select_one('.product__card-name')
        if product_name_elem:
            print(f"[SEARCH] Product name: {product_name_elem.text.strip()}")
    else:
        # Try alternative selectors
        products = soup.select('.product__card')
        if products:
            print(f"[SEARCH] FOUND {len(products)} product cards")
        else:
            print("[SEARCH] INFO - No products found")
else:
    print(f"[SEARCH] FAILED - {error}")

# ==================== SUMMARY ====================
print("\n" + "=" * 80)
print("TEST SUMMARY")
print("=" * 80)
print("""
Expected Results:
1. Ketnoitieudung: SHOULD FIND + PARSE (có sản phẩm này)
2. Visior: May not find (không chắc có hàng)
3. THB Vietnam: May not find (không chắc có hàng)
4. Mecsu: SHOULD FIND (có sản phẩm này theo screenshot)

KEY FIXES TO VERIFY:
- Ketnoitieudung: /san-pham.html?keyword= (NOT /tim-kiem?q=)
- Ketnoitieudung parse: #tab-specification table (NOT #thong-so-ky-thuat)
- THB: ?keywords= (NOT ?q=)
- Mecsu: popup triggers (no direct links)
""")
print("=" * 80)
