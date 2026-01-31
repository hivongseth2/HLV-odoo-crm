#!/usr/bin/env python3
import requests
from bs4 import BeautifulSoup

url = "https://www.milwaukeetool.com.vn/power-tools/sawing-cutting/m18-planer"
print(f"Fetching: {url}")
r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
soup = BeautifulSoup(r.content, 'html.parser')

print("--- Checking 'Đặc điểm' section ---")
# Look for header "Đặc điểm"
headers = soup.find_all(string=lambda text: text and "Đặc điểm" in text)
for h in headers:
    parent = h.find_parent('div') or h.find_parent('h3') or h.find_parent('h2')
    if parent:
        print(f"Found header in: {parent.name}, class: {parent.get('class')}")
        # Check next Sibling or parent's sibling
        
# Try generic selectors for features
features = soup.select('.features') or soup.select('#features') or soup.select('.product-features')
if features:
    print(f"Found .features or similar: {len(features)}")
    print(features[0].prettify()[:500])
else:
    print("No obvious feature class found.")

print("\n--- Inspecting Specs structure (checking columns) ---")
spec_rows = soup.select('.specification-list')
if spec_rows:
    row = spec_rows[1] # Check 2nd row (skip header if any)
    cols = row.find_all('div', recursive=False)
    print(f"Row has {len(cols)} columns")
    for i, c in enumerate(cols):
        print(f"Col {i}: {c.get_text(strip=True)[:50]}")
