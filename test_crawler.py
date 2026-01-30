#!/usr/bin/env python3
"""
Test script cho hlv_product_crawler module
Chạy local để verify trước khi push lên production
"""

import sys
import os

# Add module path
sys.path.insert(0, os.path.abspath('.'))

from custom_addons.hlv_product_crawler.models.crawler_parsers import CrawlerUtils

def test_extract_keywords():
    """Test keyword extraction"""
    print("\n=== TEST EXTRACT KEYWORDS ===")
    
    test_cases = [
        "Máy khoan động lực M18 FPD3-0 (bare) MILWAUKEE",
        "Máy cắt GWS 750-100 BOSCH",
        "Bộ mũi khoan 13 chi tiết Bosch",
    ]
    
    for product_name in test_cases:
        keywords = CrawlerUtils.extract_keywords(product_name)
        print(f"\nProduct: {product_name}")
        print(f"Keywords: {keywords}")

def test_search_ketnoitieudung():
    """Test search on ketnoitieudung.vn"""
    print("\n=== TEST KETNOITIEUDUNG.VN SEARCH ===")
    
    # Test with real product
    sku = "M18 FPD3-0"
    product_name = "Máy khoan động lực M18 FPD3-0 (bare) MILWAUKEE"
    
    print(f"\nSearching for: {sku}")
    print(f"Product name: {product_name}")
    
    url, error = CrawlerUtils.search_ketnoitieudung(sku, product_name)
    
    if url:
        print(f"✅ FOUND: {url}")
        # Try parsing
        specs, parse_error = CrawlerUtils.parse_ketnoitieudung_details(url)
        if specs:
            print(f"✅ Parsed {len(specs)} chars of specs")
        else:
            print(f"❌ Parse failed: {parse_error}")
    else:
        print(f"❌ NOT FOUND: {error}")

def test_search_visior():
    """Test search on visior.vn"""
    print("\n=== TEST VISIOR.VN SEARCH ===")
    
    sku = "M18 FPD3-0"
    product_name = "Máy khoan động lực M18 FPD3-0 (bare) MILWAUKEE"
    
    print(f"\nSearching for: {sku}")
    print(f"Product name: {product_name}")
    
    url, error = CrawlerUtils.search_visior(sku, product_name)
    
    if url:
        print(f"✅ FOUND: {url}")
        specs, parse_error = CrawlerUtils.parse_visior_details(url)
        if specs:
            print(f"✅ Parsed {len(specs)} chars of specs")
        else:
            print(f"❌ Parse failed: {parse_error}")
    else:
        print(f"❌ NOT FOUND: {error}")

def test_search_thb():
    """Test search on thbvietnam.com"""
    print("\n=== TEST THB VIETNAM SEARCH ===")
    
    sku = "M18 FPD3-0"
    product_name = "Máy khoan động lực M18 FPD3-0 (bare) MILWAUKEE"
    
    print(f"\nSearching for: {sku}")
    print(f"Product name: {product_name}")
    
    url, error = CrawlerUtils.search_thbvietnam(sku, product_name)
    
    if url:
        print(f"✅ FOUND: {url}")
        specs, parse_error = CrawlerUtils.parse_thbvietnam_details(url)
        if specs:
            print(f"✅ Parsed {len(specs)} chars of specs")
        else:
            print(f"❌ Parse failed: {parse_error}")
    else:
        print(f"❌ NOT FOUND: {error}")

def test_search_mecsu():
    """Test search on mecsu.vn"""
    print("\n=== TEST MECSU.VN SEARCH ===")
    
    sku = "M18 FPD3-0"
    product_name = "Máy khoan động lực M18 FPD3-0 (bare) MILWAUKEE"
    
    print(f"\nSearching for: {sku}")
    print(f"Product name: {product_name}")
    
    url, error = CrawlerUtils.search_mecsu(sku, product_name)
    
    if url:
        print(f"✅ FOUND: {url}")
        specs, parse_error = CrawlerUtils.parse_mecsu_details(url)
        if specs:
            print(f"✅ Parsed {len(specs)} chars of specs")
        else:
            print(f"❌ Parse failed: {parse_error}")
    else:
        print(f"❌ NOT FOUND: {error}")

if __name__ == "__main__":
    print("="*60)
    print("🧪 CRAWLER MODULE TEST SUITE")
    print("="*60)
    
    try:
        test_extract_keywords()
        test_search_ketnoitieudung()
        test_search_visior()
        test_search_thb()
        test_search_mecsu()
        
        print("\n" + "="*60)
        print("✅ TEST SUITE COMPLETED")
        print("="*60)
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
