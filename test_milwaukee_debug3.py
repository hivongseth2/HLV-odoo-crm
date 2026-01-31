#!/usr/bin/env python3
import requests
from bs4 import BeautifulSoup

url = "https://www.milwaukeetool.com.vn/catalogsearch/result/?q=M18"
r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
soup = BeautifulSoup(r.content, 'html.parser')

print("Checking .product-item-photo elements:")
photos = soup.select('.product-item-photo')
for p in photos[:3]:
    print(f"Tag: {p.name}")
    print(f"Attrs: {p.attrs}")
    if p.name == 'a':
        print(f"HREF: {p.get('href')}")
    else:
        # Check children
        a = p.find('a')
        if a:
            print(f"Child <a> HREF: {a.get('href')}")
            
print("\nChecking for ANY 'a' tag with href containing 'chi-tiet' or 'san-pham' or similar:")
links = soup.find_all('a', href=True)
count = 0
for l in links:
    href = l['href']
    if 'catalogsearch' not in href and 'javascript' not in href and '#' not in href:
        print(f"Candidate: {href}")
        count += 1
        if count > 5: break
