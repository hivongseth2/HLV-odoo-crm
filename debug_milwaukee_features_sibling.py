#!/usr/bin/env python3
import requests
from bs4 import BeautifulSoup

url = "https://www.milwaukeetool.com.vn/power-tools/sawing-cutting/m18-planer"
r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
soup = BeautifulSoup(r.content, 'html.parser')

headers = soup.find_all(string=lambda text: text and "Đặc điểm" in text)
for h in headers:
    parent = h.find_parent('div')
    if parent:
        print(f"Header found in DIV. Next sibling:")
        sibling = parent.find_next_sibling()
        if sibling:
            print(f"Tag: {sibling.name}, Class: {sibling.get('class')}")
            print(sibling.prettify()[:500])
        else:
            print("No next sibling.")
