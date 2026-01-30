#!/usr/bin/env python3
"""Simple test - no Vietnamese chars to avoid encoding issues"""

import requests
from bs4 import BeautifulSoup
import urllib.parse

print("CRAWLER TEST RESULTS")
print("=" * 60)

sku = "M18 FPD3-0"

# TEST 1: Ketnoitieudung
print("\n1. KETNOITIEUDUNG.VN")
url = f"https://www.ketnoitieudung.vn/san-pham.html?keyword={urllib.parse.quote(sku)}"
print(f"URL: {url}")

try:
    r = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
    soup = BeautifulSoup(r.content, 'html.parser')
    
    product = soup.select_one('.product-card__name a')
    if product:
        product_url = product.get('href')
        if not product_url.startswith('http'):
            product_url = f"https://www.ketnoitieudung.vn{product_url}"
        print(f"SEARCH: OK - Found product")
        print(f"Product URL: {product_url}")
        
        # Test parse
        r2 = requests.get(product_url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        soup2 = BeautifulSoup(r2.content, 'html.parser')
        
        specs = soup2.select_one('#tab-specification table')
        if specs:
            rows = specs.find_all('tr')
            print(f"PARSE: OK - Found {len(rows)} spec rows")
        else:
            print("PARSE: FAIL - No specs table found")
    else:
        print("SEARCH: FAIL - No product found")
except Exception as e:
    print(f"ERROR: {e}")

# TEST 2: THB Vietnam
print("\n2. THB VIETNAM")
url = f"https://thbvietnam.com/tim-kiem?keywords={urllib.parse.quote(sku)}"
print(f"URL: {url}")

try:
    r = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
    soup = BeautifulSoup(r.content, 'html.parser')
    
    product = soup.select_one('.item a')
    if product:
        print(f"SEARCH: OK - Found product")
        print(f"Product URL: {product.get('href')}")
    else:
        print("SEARCH: No product (may not have this item)")
except Exception as e:
    print(f"ERROR: {e}")

# TEST 3: Mecsu
print("\n3. MECSU.VN")
url = f"https://mecsu.vn/site?keyword={urllib.parse.quote(sku)}"
print(f"URL: {url}")

try:
    r = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
    soup = BeautifulSoup(r.content, 'html.parser')
    
    popups = soup.select('.mecsu-button-popup-lg[value*="product-quick-view"]')
    if popups:
        print(f"SEARCH: OK - Found {len(popups)} products")
        print("Note: Mecsu uses popups (no direct product links)")
    else:
        print("SEARCH: No products found")
except Exception as e:
    print(f"ERROR: {e}")

# TEST 4: Visior
print("\n4. VISIOR.VN")
url = f"https://visior.vn/search?q={urllib.parse.quote(sku)}"
print(f"URL: {url}")

try:
    r = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
    soup = BeautifulSoup(r.content, 'html.parser')
    
    product = soup.select_one('.product-item a')
    if product:
        print(f"SEARCH: OK - Found product")
        print(f"Product URL: {product.get('href')}")
    else:
        print("SEARCH: No product (may not have this item)")
except Exception as e:
    print(f"ERROR: {e}")

print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print("Expected:")
print("- Ketnoitieudung: PASS (has product)")
print("- Mecsu: PASS (has product)")
print("- THB & Visior: May not have product")
print("=" * 60)
