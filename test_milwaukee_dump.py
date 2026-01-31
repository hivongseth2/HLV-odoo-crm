#!/usr/bin/env python3
"""
Dump Milwaukee product item structure
"""
import requests
from bs4 import BeautifulSoup

url = "https://www.milwaukeetool.com.vn/catalogsearch/result/?q=M18"
print(f"Fetching: {url}")
r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
soup = BeautifulSoup(r.content, 'html.parser')

item = soup.select_one('.product-item')
if item:
    print(item.prettify())
else:
    print("No .product-item found")
