#!/usr/bin/env python3
"""
Test CORRECTED Mecsu fix with title filter
"""
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
print("TESTING MECSU FIX - WITH TITLE FILTER")
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
    
    # Check all popup buttons first
    all_popups = soup.select('.mecsu-button-popup-lg')
    print(f"\nFound {len(all_popups)} popup buttons:")
    for i, btn in enumerate(all_popups):
        print(f"  [{i}] title=\"{btn.get('title')}\" value=\"{btn.get('value')}\"")
    
    # Now find the CORRECT one
    popup_btn = soup.select_one('a.mecsu-button-popup-lg[title="Thông số kỹ thuật"]')
    if popup_btn:
        print("\n✓ Found CORRECT popup button (Thông số kỹ thuật)")
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
                print("\n3. FIND 'Xem chi tiết' LINK")
                detail_links = quick_soup.select('a[href*="/chi-tiet/"]')
                print(f"Found {len(detail_links)} chi-tiet links")
                
                for link in detail_links:
                    text = link.get_text()
                    if 'Xem chi tiết' in text:
                        href = link.get('href')
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
                                    print("\n✅ ✅ ✅ MECSU FIX WORKS PERFECTLY! ✅ ✅ ✅")
                                    break
                                else:
                                    print("✗ No table in #information")
                            else:
                                print("✗ No #information section")
                        else:
                            print(f"✗ Parse error: {detail_err}")
                        break
                else:
                    print("✗ No 'Xem chi tiết' link found")
            else:
                print(f"✗ Quick-view error: {quick_err}")
        else:
            print("✗ Quick-view path doesn't contain 'product-quick-view'")
    else:
        print("\n✗ No 'Thông số kỹ thuật' button found")
else:
    print(f"✗ Search error: {err}")

print("\n" + "=" * 80)
