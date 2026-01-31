#!/usr/bin/env python3
import sys
sys.path.insert(0, 'd:/HLV/HLV-odoo-crm/custom_addons/hlv_product_crawler/models')
from crawler_parsers import CrawlerUtils

url = "https://www.milwaukeetool.com.vn/power-tools/sawing-cutting/m18-planer"
print(f"Testing parse for: {url}")

specs, err = CrawlerUtils.parse_milwaukee_details(url)
if specs:
    print("✓ Parse SUCCESS")
    if "Đặc điểm nổi bật" in specs:
        print("✓ FOUND Features section")
    else:
        print("✗ MISSING Features section")
        
    print("\n--- Preview ---")
    print(specs[500:1500]) # Print middle part where features might be
else:
    print(f"✗ Parse FAILED: {err}")
