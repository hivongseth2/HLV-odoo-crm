#!/usr/bin/env python3
"""
Debug Milwaukee search
"""
import requests
from bs4 import BeautifulSoup
import urllib.parse

sku = "M18 FPD3"
base_url = "https://www.milwaukeetool.com.vn"
search_url = f"{base_url}/catalogsearch/result/?q={urllib.parse.quote(sku)}"

print(f"Fetching: {search_url}")
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

r = requests.get(search_url, headers=headers)
print(f"Status: {r.status_code}")

if r.status_code == 200:
    soup = BeautifulSoup(r.content, 'html.parser')
    
    # Check for products
    items = soup.select('.product-item-link')
    print(f"Found {len(items)} product links")
    
    for item in items[:3]:
        print(f"  Link: {item.get('href')} | Text: {item.get_text(strip=True)}")
        
    # Check if empty
    if not items:
        print("\nPage content preview (first 1000 chars):")
        print(soup.prettify()[:1000])
else:
    print("Request failed")
