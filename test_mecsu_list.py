#!/usr/bin/env python3
"""
Check structure of Mecsu .additional__info_list
"""
import requests
from bs4 import BeautifulSoup

url = "https://mecsu.vn/chi-tiet/may-khoan-dong-luc-18v-158nm-2100-vongphut-milwaukee-m18-fpd3-0.YrqZl"

print("Fetching:", url)
r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
soup = BeautifulSoup(r.content, 'html.parser')

specs_list = soup.select_one('.additional__info_list')
if specs_list:
    print("✓ Found .additional__info_list")
    print("\nHTML structure:")
    print(specs_list.prettify()[:1000])
    
    print("\n\nExtracting data:")
    items = specs_list.find_all('li')
    print(f"Found {len(items)} list items")
    
    for i, item in enumerate(items[:5]):  # First 5
        label = item.select_one('.label')
        value = item.select_one('.value')
        print(f"[{i}] label: {label.get_text(strip=True) if label else 'N/A'}")
        print(f"    value: {value.get_text(strip=True) if value else 'N/A'}")
else:
    print("✗ No .additional__info_list found")
