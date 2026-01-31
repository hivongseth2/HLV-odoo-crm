#!/usr/bin/env python3
import requests
from bs4 import BeautifulSoup

url = "https://www.milwaukeetool.com.vn/power-tools/sawing-cutting/m18-planer"
r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
soup = BeautifulSoup(r.content, 'html.parser')

specs = soup.select('.specification-list')
print(f"Found {len(specs)} .specification-list elements (rows).")

for i, spec in enumerate(specs):
    print(f"Row [{i}]:")
    # Get text of children
    children = spec.find_all(True, recursive=False)
    texts = [c.get_text(strip=True) for c in children]
    print(f"  Cells: {texts}")
