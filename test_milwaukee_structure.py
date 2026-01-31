#!/usr/bin/env python3
import requests
from bs4 import BeautifulSoup

url = "https://www.milwaukeetool.com.vn/power-tools/sawing-cutting/m18-planer"
r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
soup = BeautifulSoup(r.content, 'html.parser')

spec_list = soup.select_one('.specification-list')
if spec_list:
    print(f"Spec list tag: {spec_list.name}, classes: {spec_list.get('class')}")
    children = spec_list.find_all(True, recursive=False)
    print(f"Children count: {len(children)}")
    for i, child in enumerate(children):
        print(f"Child [{i}] tag: {child.name}, class: {child.get('class')}")
        subchildren = child.find_all(True, recursive=False)
        print(f"  Subchildren count: {len(subchildren)}")
        for j, sub in enumerate(subchildren):
            print(f"    Sub [{j}] text: {sub.get_text(strip=True)[:50]}")
else:
    print("No .specification-list")
