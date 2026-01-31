#!/usr/bin/env python3
import requests
from bs4 import BeautifulSoup
import urllib.parse

sku = "M18 FPD3"
search_url = f"https://www.milwaukeetool.com.vn/catalogsearch/result/?q={urllib.parse.quote(sku)}"
print(f"Fetching: {search_url}")
r = requests.get(search_url, headers={'User-Agent': 'Mozilla/5.0'})
soup = BeautifulSoup(r.content, 'html.parser')

print("Checking .product-item-photo:")
photos = soup.select('.product-item-photo')
print(f"Found {len(photos)}")
for p in photos:
    print(f"Href: {p.get('href')}")
    
print("\nChecking .product-item-link:")
links = soup.select('.product-item-link')
print(f"Found {len(links)}")
for l in links:
    print(l.get_text(strip=True))

print("\nChecking any message:")
msg = soup.select_one('.message.notice')
if msg:
    print(f"Message: {msg.get_text(strip=True)}")
