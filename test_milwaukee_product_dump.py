#!/usr/bin/env python3
import requests
from bs4 import BeautifulSoup

url = "https://www.milwaukeetool.com.vn/power-tools/sawing-cutting/m18-planer"
print(f"Fetching: {url}")
r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
soup = BeautifulSoup(r.content, 'html.parser')

print("Checking .specification-list:")
spec = soup.select_one('.specification-list')
if spec:
    print("✓ Found .specification-list")
else:
    print("✗ No .specification-list")
    
# Check for scripts with product data
print("\nChecking scripts:")
scripts = soup.find_all('script')
for s in scripts:
    if 'specification' in s.get_text() or 'attributes' in s.get_text():
        print("Found keywords in script:")
        print(s.get_text()[:200] + "...")
