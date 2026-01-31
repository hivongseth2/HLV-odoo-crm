#!/usr/bin/env python3
"""
Debug Milwaukee search - Inspection
"""
import requests
from bs4 import BeautifulSoup
import urllib.parse

sku = "M18 FPD3"
base_url = "https://www.milwaukeetool.com.vn"
search_url = f"{base_url}/catalogsearch/result/?q={urllib.parse.quote(sku)}"

print(f"Fetching: {search_url}")
headers = {
    'User-Agent': 'Mozilla/5.0'
}

r = requests.get(search_url, headers=headers)
soup = BeautifulSoup(r.content, 'html.parser')

items = soup.select('.product-item-link')
print(f"Found {len(items)} items")

for i, item in enumerate(items[:3]):
    print(f"\nItem [{i}]:")
    print(f"  Tag: {item.name}")
    print(f"  Attrs: {item.attrs}")
    print(f"  Text: {item.get_text(strip=True)[:50]}")
    
    # Try finding 'a' parent or child if it's not 'a'
    if item.name != 'a':
        parent_a = item.find_parent('a')
        if parent_a:
            print(f"  Parent <a> href: {parent_a.get('href')}")
            
# Also check for .product-item-photo which is usually a link
print("\nChecking .product-item-photo:")
photos = soup.select('.product-item-photo')
for p in photos[:3]:
    print(f"  href: {p.get('href')}")
