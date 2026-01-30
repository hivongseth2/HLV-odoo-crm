#!/usr/bin/env python3
"""
Better extraction of Mecsu specs list
"""
import requests
from bs4 import BeautifulSoup

url = "https://mecsu.vn/chi-tiet/may-khoan-dong-luc-18v-158nm-2100-vongphut-milwaukee-m18-fpd3-0.YrqZl"

print("Fetching:", url)
r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
soup = BeautifulSoup(r.content, 'html.parser')

specs_list = soup.select_one('.additional__info_list')
if specs_list:
    print("✓ Found .additional__info_list\n")
    
    # Try different item selectors
    items = specs_list.find_all('li')
    print(f"Method 1 - find_all('li'): {len(items)} items")
    
    items2 = specs_list.select('.additional__info_list--item')
    print(f"Method 2 - .additional__info_list--item: {len(items2)} items")
    
    items3 = specs_list.select('li.additional__info_list--item')
    print(f"Method 3 - li.additional__info_list--item: {len(items3)} items\n")
    
    # Use best method
    best_items = items if len(items) > len(items3) else items3
    
    print(f"Extracting {len(best_items)} items:\n")
    for i, item in enumerate(best_items):
        # Try different label/value selectors
        label = item.select_one('.info__list--item-head strong') or item.select_one('.info__list--item-head') or item.select_one('strong')
        value = item.select_one('.info__list--item-content')
        
        label_text = label.get_text(strip=True) if label else "N/A"
        value_text = value.get_text(strip=True) if value else "N/A"
        
        print(f"[{i}] {label_text}: {value_text}")
else:
    print("✗ No .additional__info_list found")
