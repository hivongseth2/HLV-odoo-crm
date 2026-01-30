#!/usr/bin/env python3
"""
Standalone test cho crawler logic
Không cần Odoo dependencies
"""

import requests
from bs4 import BeautifulSoup
import urllib.parse
import re

def extract_keywords(product_name):
    """Extract search keywords from product name"""
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

def search_site(base_url, search_path, sku, product_name, selectors):
    """Generic search function"""
    # Build queries
    queries = [sku] if sku else []
    
    if sku:
        queries.extend([
            sku.replace('-', '').replace(' ', ''),
            sku.upper(),
            sku.lower(),
        ])
    
    if product_name:
        queries.append(product_name)
        keywords = extract_keywords(product_name)
        if len(keywords) >= 2:
            queries.append(' '.join(keywords[:2]))
        if keywords:
            queries.append(keywords[0])
    
    print(f"  Trying {len(queries)} query variations:")
    for i, query in enumerate(queries, 1):
        print(f"    {i}. '{query}'")
        search_url = f"{base_url}{search_path}{urllib.parse.quote(query)}"
        
        try:
            response = requests.get(search_url, timeout=5, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Try each selector
                for selector in selectors:
                    product_item = soup.select_one(selector)
                    if product_item:
                        href = product_item.get('href')
                        if href:
                            if not href.startswith('http'):
                                href = f"{base_url}{href}"
                            print(f"       ✅ FOUND with '{query}': {href}")
                            return href
                
        except Exception as e:
            print(f"       ❌ Error: {e}")
            continue
    
    return None

# Test cases
print("="*70)
print("🧪 CRAWLER STANDALONE TEST")
print("="*70)

sku = "M18 FPD3-0"
product_name = "Máy khoan động lực M18 FPD3-0 (bare) MILWAUKEE"

print(f"\nProduct: {product_name}")
print(f"SKU: {sku}")

# Test keyword extraction
print("\n--- KEYWORD EXTRACTION ---")
keywords = extract_keywords(product_name)
print(f"Extracted keywords: {keywords}")

# Test Ketnoitieudung.vn
print("\n--- KETNOITIEUDUNG.VN ---")
url = search_site(
    "https://www.ketnoitieudung.vn",
    "/tim-kiem?q=",
    sku,
    product_name,
    ['.product-item a', 'a[href*="/san-pham/"]']
)
if url:
    print(f"✅ SUCCESS: {url}")
else:
    print("❌ NOT FOUND")

# Test Visior.vn
print("\n--- VISIOR.VN ---")
url = search_site(
    "https://visior.vn",
    "/search?q=",
    sku,
    product_name,
    ['.product-block .name a', '.product-item a', 'a[href*="/san-pham/"]']
)
if url:
    print(f"✅ SUCCESS: {url}")
else:
    print("❌ NOT FOUND")

# Test THB Vietnam
print("\n--- THB VIETNAM ---")
url = search_site(
    "https://thbvietnam.com",
    "/tim-kiem?q=",
    sku,
    product_name,
    ['.product-item-link', '.product-item a', 'a[href*="/san-pham/"]']
)
if url:
    print(f"✅ SUCCESS: {url}")
else:
    print("❌ NOT FOUND")

# Test Mecsu.vn
print("\n--- MECSU.VN ---")
url = search_site(
    "https://mecsu.vn",
    "/site?keyword=",
    sku,
    product_name,
    ['.mecsu-button-popup-lg', '.product__items a', 'a[href*="/chi-tiet/"]']
)
if url:
    print(f"✅ SUCCESS: {url}")
else:
    print("❌ NOT FOUND")

print("\n" + "="*70)
print("✅ TEST COMPLETED")
print("="*70)
