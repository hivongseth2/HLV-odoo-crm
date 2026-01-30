#!/usr/bin/env python3
"""
Test COMPLETE Mecsu flow (search + parse)
"""
import sys
sys.path.insert(0, 'd:/HLV/HLV-odoo-crm/custom_addons/hlv_product_crawler/models')

from crawler_parsers import CrawlerUtils

print("=" * 80)
print("TESTING COMPLETE MECSU FLOW")
print("=" * 80)

sku = "M18 FPD3-0"

# Step 1: Search
print("\n1. SEARCH")
url, err = CrawlerUtils.search_mecsu(sku)
if url:
    print(f"✓ Found URL: {url}")
    
    # Step 2: Parse
    print("\n2. PARSE SPECS")
    specs_html, parse_err = CrawlerUtils.parse_mecsu_details(url)
    if specs_html:
        print(f"✓ Got specs HTML ({len(specs_html)} chars)")
        print("\nPreview:")
        print(specs_html[:500])
        print("\n✅ ✅ ✅ MECSU COMPLETE FLOW WORKS! ✅ ✅ ✅")
    else:
        print(f"✗ Parse error: {parse_err}")
else:
    print(f"✗ Search error: {err}")

print("\n" + "=" * 80)
