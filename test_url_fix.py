#!/usr/bin/env python3
"""Quick test với URL đã fix"""

import requests
from bs4 import BeautifulSoup
import urllib.parse

# Test với URL ĐÃ FIX
print("=" * 70)
print("🧪 TESTING FIXED URLs")
print("=" * 70)

sku = "M18 FPD3-0"

# Test Ketnoitieudung với URL MỚI
print("\n1. KETNOITIEUDUNG.VN (FIXED URL)")
print(f"   Query: {sku}")

# OLD (sai): /tim-kiem?q=
old_url = f"https://www.ketnoitieudung.vn/tim-kiem?q={urllib.parse.quote(sku)}"
print(f"   ❌ OLD URL: {old_url}")

# NEW (đúng): /san-pham.html?keyword=
new_url = f"https://www.ketnoitieudung.vn/san-pham.html?keyword={urllib.parse.quote(sku)}"
print(f"   ✅ NEW URL: {new_url}")

try:
    response = requests.get(new_url, timeout=10, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    
    if response.status_code == 200:
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Try new selector
        product = soup.select_one('.product-card__name a')
        if product:
            print(f"   ✅ FOUND: {product.get('href')}")
            print(f"   Product: {product.text.strip()}")
        else:
            print("   ❌ No product found with new selector")
    else:
        print(f"   ❌ HTTP {response.status_code}")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Test THB với parameter FIX
print("\n2. THB VIETNAM (FIXED PARAMETER)")
print(f"   Query: {sku}")

# OLD (sai): ?q=
old_thb = f"https://thbvietnam.com/tim-kiem?q={urllib.parse.quote(sku)}"
print(f"   ❌ OLD: {old_thb}")

# NEW (đúng): ?keywords=
new_thb = f"https://thbvietnam.com/tim-kiem?keywords={urllib.parse.quote(sku)}"
print(f"   ✅ NEW: {new_thb}")

try:
    response = requests.get(new_thb, timeout=10, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    
    if response.status_code == 200:
        soup = BeautifulSoup(response.content, 'html.parser')
        product = soup.select_one('.item a')
        if product:
            print(f"   ✅ FOUND: {product.get('href')}")
        else:
            print("   ❌ No product found")
    else:
        print(f"   ❌ HTTP {response.status_code}")
except Exception as e:
    print(f"   ❌ Error: {e}")

print("\n" + "=" * 70)
print("TEST DONE")
print("=" * 70)
