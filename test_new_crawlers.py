#!/usr/bin/env python3
"""
Test Milwaukee and Bosch crawlers
"""
import sys
import logging
# Mock Odoo environment
sys.path.insert(0, 'd:/HLV/HLV-odoo-crm/custom_addons/hlv_product_crawler/models')
from crawler_parsers import CrawlerUtils

# Config logging
logging.basicConfig(level=logging.INFO)

def test_site(name, search_func, parse_func, sku):
    print("\n" + "="*80)
    print(f"TESTING {name.upper()}")
    print("="*80)
    
    # 1. Search
    print(f"\n1. SEARCH: {sku}")
    url, err = search_func(sku)
    if url:
        print(f"✓ Found URL: {url}")
        
        # 2. Parse
        print(f"\n2. PARSE")
        specs, parse_err = parse_func(url)
        if specs:
            print(f"✓ Parsed specs ({len(specs)} chars)")
            print("Preview:")
            print(specs[:500] + "...")
        else:
            print(f"✗ Parse error: {parse_err}")
    else:
        print(f"✗ Search error: {err}")

# Test Milwaukee
test_site("Milwaukee", CrawlerUtils.search_milwaukee, CrawlerUtils.parse_milwaukee_details, "M18 FPD3")

# Test Bosch
test_site("Bosch", CrawlerUtils.search_bosch, CrawlerUtils.parse_bosch_details, "GSB 185-LI")
