#!/usr/bin/env python3
"""
Script test để debug MISA fetch response
Chạy từ Odoo shell:
  $ odoo shell -c /path/to/config.conf
  >>> exec(open('/full/path/to/test_misa_fetch.py').read())
"""

import json
import requests
import copy

# Test với order này
TEST_ORDER_NAME = "DH115524948215998"

# Payload template giống script chính
PAYLOAD_TEMPLATE = {
    "Columns": "SUQsUmV2ZW51ZVN0YXR1c0lELFJldmVudWVTdGF0dXNJRFRleHQsQWNjb3VudElELEFjY291bnRJRFRleHQsU2FsZU9yZGVyTm8sU2FsZU9yZGVyTmFtZSxTYWxlT3JkZXJBbW91bnQsU2FsZU9yZGVyRGF0ZSxCb29rRGF0ZSxPd25lcklELE93bmVySURUZXh0LE9yZ2FuaXphdGlvblVuaXRJRCxPcmdhbml6YXRpb25Vbml0SURUZXh0LERlbGl2ZXJ5U3RhdHVzSUQsRGVsaXZlcnlTdGF0dXNJRFRleHQsUGF5U3RhdHVzSUQsUGF5U3RhdHVzSURUZXh0LEJpbGxpbmdDb3VudHJ5SUQsQmlsbGluZ0NvdW50cnlJRFRleHQsQmlsbGluZ1Byb3ZpbmNlSUQsQmlsbGluZ1Byb3ZpbmNlSURUZXh0LEJpbGxpbmdEaXN0cmljdElELEJpbGxpbmdEaXN0cmljdElEVGV4dCxCaWxsaW5nV2FyZElELEJpbGxpbmdXYXJkSURUZXh0LERlbGl2ZXJ5T3JkZXJOdW1iZXIsUGhvbmUsQWNjb3VudFRlbCxTaGlwcGluZ0FkZHJlc3MsRm9ybUxheW91dElELEZvcm1MYXlvdXRJRFRleHQsQWNjb3VudE93bmVySUQsSXNQYXJlbnRTYWxlT3JkZXIsT3Bwb3J0dW5pdHlJRCxPcHBvcnR1bml0eUlEVGV4dCxSb2xlT3duZXJJRCxJc1VzZUN1cnJlbmN5LEV4Y2hhbmdlUmF0ZSxQYXJlbnRJRCxQYXJlbnRJRFRleHQsUXVvdGVJRCxRdW90ZUlEVGV4dCxDb250YWN0SUQsQ29udGFjdElEVGV4dCxFYXJuaW5nUG9pbnQsRXhjaGFuZ2VQb2ludCxQYWlkRGF0ZSxEZWxpdmVyeURhdGUsQXBwcm92ZWRTdGF0dXNJRCxUYWdJRCxUYWdJRFRleHQsRXhwZWN0ZWREZWxpdmVyeURhdGUsRGVsaXZlcnlQYXJ0bmVySUQsRGVsaXZlcnlQYXJ0bmVyU3RhdHVzSUQsRGVsaXZlcnlQYXJ0bmVyU3RhdHVzSURUZXh0LEVjb21tZXJjZUlELFByb2R1Y3Rpb25Db25maXJtYXRpb25TdGF0dXNJRCxQcm9kdWN0aW9uQ29uZmlybWF0aW9uU3RhdHVzSURUZXh0LFByb2R1Y3Rpb25EYXRlLFNhbGVPcmRlclR5cGVJRA==",
    "CustomColumns": "Q3VzdG9tRmllbGQyMw==",
    "Sorts": [{"SortBy": "ModifiedDate", "Type": 0, "SortDirection": 1}],
    "Start": 0,
    "Page": 1,
    "PageSize": 20,
    "Filters": [],
    "Formula": "",
    "LayoutCode": "SaleOrder",
    "DefaultTotal": True,
    "IsMappingData": False,
    "MappingValueObject": {},
    "IsApproved": False,
    "CustomPagingData": {},
    "IsUsedELTS": True,
    "ListGmailPage": [],
    "ListFacebookPage": {},
    "IsListPaging": True,
    "IsGetCache": True,
    "IsCheckInactive": False,
    "IsConverted": False,
    "SessionID": "55dc65e7-41ee-fcb6-fd21-7118cb82cb3c",
    "LayoutCodeCheckPermission": "SaleOrder",
    "AISearchKeyword": ""
}

MISA_GRID_URL = "https://amisapp.misa.vn/crm/g1/api/business/SaleOrder/Grid"

def test_fetch():
    """Test fetch order từ MISA"""
    
    # Lấy headers từ Odoo
    try:
        misa_utils = env['misa.api.utils']
        misa_config = env['misa.config']
        crm_token = misa_utils._fetch_login_crm_token()
        misa_headers = misa_config.get_crm_header(crm_token)
        
        print("\n" + "="*80)
        print("📝 TEST MISA FETCH")
        print("="*80)
        
        print("\n📌 Headers nhận được:")
        for key, val in misa_headers.items():
            if key.lower() == 'authorization':
                print(f"  {key}: Bearer {val[:50]}...")
            else:
                print(f"  {key}: {val}")
        
        # Tạo payload
        payload = copy.deepcopy(PAYLOAD_TEMPLATE)
        payload['AISearchKeyword'] = TEST_ORDER_NAME
        
        print(f"\n📦 Payload gửi đi:")
        print(f"  AISearchKeyword: {payload.get('AISearchKeyword')}")
        print(f"  Filters: {payload.get('Filters')}")
        print(f"  PageSize: {payload.get('PageSize')}")
        print(f"  SessionID: {payload.get('SessionID')}")
        
        # Gửi request
        print(f"\n🔗 Gọi API: {MISA_GRID_URL}")
        response = requests.post(
            MISA_GRID_URL,
            headers=misa_headers,
            json=payload,
            timeout=30
        )
        response.raise_for_status()
        
        # Parse response
        data = response.json()
        print(f"\n✅ Response status code: {response.status_code}")
        print(f"✅ Response Success: {data.get('Success')}")
        print(f"✅ Response Message: {data.get('Message', 'N/A')}")
        
        items = data.get('Data', [])
        print(f"✅ Số items return: {len(items)}")
        
        if items:
            print(f"\n📋 Chi tiết items return:")
            for idx, item in enumerate(items[:5]):  # Show first 5
                print(f"\n  [{idx}] Item:")
                print(f"      SaleOrderNo: {item.get('SaleOrderNo', 'N/A')}")
                print(f"      SaleOrderName: {item.get('SaleOrderName', 'N/A')[:50]}")
                print(f"      ShippingAddress: {item.get('ShippingAddress', 'N/A')[:80]}")
            
            if len(items) > 5:
                print(f"\n  ... và {len(items) - 5} items khác")
        
        print("\n" + "="*80)
        
        # Lưu response vào file để inspect sau
        with open('/tmp/misa_response.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print("✅ Full response đã save vào /tmp/misa_response.json")
        
    except Exception as e:
        print(f"\n❌ Lỗi: {str(e)}")
        import traceback
        traceback.print_exc()

# Chạy test
test_fetch()
