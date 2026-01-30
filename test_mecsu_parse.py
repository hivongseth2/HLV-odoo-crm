#!/usr/bin/env python3
"""
Debug Mecsu detail page structure
"""
import requests
from bs4 import BeautifulSoup

url = "https://mecsu.vn/chi-tiet/may-khoan-dong-luc-18v-158nm-2100-vongphut-milwaukee-m18-fpd3-0.YrqZl"

print("Fetching:", url)
r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
soup = BeautifulSoup(r.content, 'html.parser')

print("\n1. Check #information:")
info = soup.select_one('#information')
if info:
    print("  ✓ Found #information")
    print(f"  Children: {[child.name for child in info.children if child.name]}")
    tables = info.select('table')
    print(f"  Tables: {len(tables)}")
else:
    print("  ✗ No #information")

print("\n2. Check .additional__info_list:")
ail = soup.select_one('.additional__info_list')
if ail:
    print("  ✓ Found .additional__info_list")
    print(f"  Text preview: {ail.get_text()[:200]}")
else:
    print("  ✗ No .additional__info_list")

print("\n3. Check .product__details--info__table:")
pdit = soup.select_one('.product__details--info__table')
if pdit:
    print("  ✓ Found .product__details--info__table")
    print(f"  Text preview: {pdit.get_text()[:200]}")
else:
    print("  ✗ No .product__details--info__table")

print("\n4. Find ALL tables:")
all_tables = soup.select('table')
print(f"Total tables: {len(all_tables)}")
for i, table in enumerate(all_tables):
    parent_id = table.parent.get('id') if table.parent else None
    parent_class = table.parent.get('class') if table.parent else None
    rows = len(table.find_all('tr'))
    print(f"  [{i}] parent_id={parent_id} parent_class={parent_class} rows={rows}")

print("\n5. Check for any specs-related divs:")
specs_divs = soup.select('[id*="spec"], [class*="spec"], [id*="information"], [class*="information"]')
print(f"Found {len(specs_divs)} specs-related elements")
for elem in specs_divs[:5]:
    print(f"  {elem.name}#{elem.get('id')} .{elem.get('class')}")
