#!/usr/bin/env python3
"""
Quick test for Mecsu fix and Hoanglongvu crawler
"""
import re
import requests
from bs4 import BeautifulSoup
import urllib.parse

def fetch_url(url):
    try:
        r = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        if r.status_code == 200:
            return r.content, None
        return None, f"HTTP {r.status_code}"
    except Exception as e:
        return None, str(e)

print("=" * 80)
print("QUICK TEST - MECSU FIX & HOANGLONGVU")
print("=" * 80)

sku = "M18 FPD3-0"

# TEST 1: Mecsu - check for popup button with product info
print("\n1. MECSU SEARCH")
url = f"https://mecsu.vn/site?keyword={urllib.parse.quote(sku)}"
print(f"URL: {url}")

html, err = fetch_url(url)
if html:
    soup = BeautifulSoup(html, 'html.parser')
    
    # Check for popup button
    popup_btn = soup.select_one('.mecsu-button-popup-lg')
    if popup_btn:
        value = popup_btn.get('value')
        print(f"FOUND popup button with value: {value}")
        
        # Extract product ID from value attribute
        # Format: "/explore/product-quick-view?id=12345" or similar
        if value and 'id=' in value:
            product_id = value.split('id=')[1].split('&')[0]
            print(f"Extracted product ID: {product_id}")
        else:
            print("Could not extract ID from value")
    
    # Also check if there are any chi-tiet links (fallback)
    detail_links = soup.select('a[href*="/chi-tiet/"]')
    print(f"Found {len(detail_links)} /chi-tiet/ links")
    if detail_links:
        print(f"First link: {detail_links[0].get('href')}")
else:
    print(f"ERROR: {err}")

# TEST 2: Hoanglongvu search
print("\n2. HOANGLONGVU SEARCH")
url = f"https://hoanglongvu.com/?s={urllib.parse.quote(sku)}&post_type=product"
print(f"URL: {url}")

html, err = fetch_url(url)
if html:
    soup = BeautifulSoup(html,'html.parser')
    
    products = soup.select('.product-small')
    print(f"Found {len(products)} product items")
    
    if products:
        first = products[0]
        link = first.select_one('.title a') or first.select_one('a')
        if link:
            print(f"Product link: {link.get('href')}")
            print(f"Product name: {link.text.strip()}")
            
            # Test parse
            product_url = link.get('href')
            print(f"\n  Testing parse from: {product_url}")
            detail_html, detail_err = fetch_url(product_url)
            if detail_html:
                detail_soup = BeautifulSoup(detail_html, 'html.parser')
                specs_table = detail_soup.select_one('table.w-100')
                if specs_table:
                    rows = specs_table.find_all('tr')
                    print(f"  FOUND specs table with {len(rows)} rows")
                else:
                    print("  Specs table NOT FOUND")
    else:
        print("No products found")
else:
    print(f"ERROR: {err}")

print("\n" + "=" * 80)
