#!/usr/bin/env python3
"""
Test Mecsu fix with 2-step fetch
"""
import re
import requests
from bs4 import BeautifulSoup
import urllib.parse

def fetch_url(url):
    try:
        r = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        if r.status_code == 200:
            return r.content, None
        return None, f"HTTP {r.status_code}"
    except Exception as e:
        return None, str(e)

print("=" * 80)
print("TESTING MECSU 2-STEP FETCH FIX")
print("=" * 80)

sku = "M18 FPD3-0"
base_url = "https://mecsu.vn"

# Step 1: Search
print("\n1. SEARCH FOR PRODUCT")
search_url = f"{base_url}/site?keyword={urllib.parse.quote(sku)}"
print(f"URL: {search_url}")

html, err = fetch_url(search_url)
if html:
    soup = BeautifulSoup(html, 'html.parser')
    
    popup_btn = soup.select_one('.mecsu-button-popup-lg')
    if popup_btn:
        print("✓ Found popup button")
        quick_view_path = popup_btn.get('value')
        print(f"  Quick-view path: {quick_view_path}")
        
        if quick_view_path and 'product-quick-view' in quick_view_path:
            # Step 2: Fetch quick-view
            print("\n2. FETCH QUICK-VIEW")
            quick_view_url = f"{base_url}{quick_view_path}"
            print(f"URL: {quick_view_url}")
            
            quick_html, quick_err = fetch_url(quick_view_url)
            if quick_html:
                quick_soup = BeautifulSoup(quick_html, 'html.parser')
                
                # Step 3: Find detail link
                print("\n3. FIND PRODUCT DETAIL LINK")
                detail_link = quick_soup.select_one('a[href*="/chi-tiet/"]')
                if detail_link:
                    href = detail_link.get('href')
                    full_url = f"{base_url}{href}" if not href.startswith('http') else href
                    print(f"✓ Found product URL: {full_url}")
                    
                    # Step 4: Test parse
                    print("\n4. TEST PARSE SPECS")
                    detail_html, detail_err = fetch_url(full_url)
                    if detail_html:
                        detail_soup = BeautifulSoup(detail_html, 'html.parser')
                        
                        info_section = detail_soup.select_one('#information')
                        if info_section:
                            table = info_section.select_one('table')
                            if table:
                                rows = table.find_all('tr')
                                print(f"✓ Found specs table with {len(rows)} rows")
                                print("\n✅ MECSU FIX WORKS!")
                            else:
                                print("✗ No table in #information")
                        else:
                            print("✗ No #information section")
                    else:
                        print(f"✗ Parse error: {detail_err}")
                else:
                    print("✗ No /chi-tiet/ link in quick-view")
            else:
                print(f"✗ Quick-view error: {quick_err}")
        else:
            print("✗ Quick-view path doesn't contain 'product-quick-view'")
    else:
        print("✗ No popup button found")
else:
    print(f"✗ Search error: {err}")

print("\n" + "=" * 80)
