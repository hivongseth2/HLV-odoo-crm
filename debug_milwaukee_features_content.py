#!/usr/bin/env python3
import requests
from bs4 import BeautifulSoup

url = "https://www.milwaukeetool.com.vn/power-tools/sawing-cutting/m18-planer"
r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
soup = BeautifulSoup(r.content, 'html.parser')

# Search for feature text likely to be present
# M18 Planer check. M18 Planer features?
# Search for generic milwaukee feature keywords or just dump list items
lis = soup.find_all('li')
found = False
for li in lis:
    text = li.get_text(strip=True)
    if "M18" in text and len(text) > 10 and len(text) < 200:
        print(f"Found LI with 'M18': {text}")
        parent = li.find_parent('ul') or li.find_parent('div')
        if parent:
            print(f"Parent tag: {parent.name}, class: {parent.get('class')}")
            found = True
            break

if not found:
    print("Searching for 'Đặc điểm' parent's content again...")
    headers = soup.find_all(string=lambda text: text and "Đặc điểm" in text)
    for h in headers:
        parent = h.find_parent('div')
        if parent:
             # Dump parent's parent content structure
             grandparent = parent.parent
             if grandparent:
                 print(f"Grandparent tag: {grandparent.name}, class: {grandparent.get('class')}")
                 print(grandparent.prettify()[:1000])
